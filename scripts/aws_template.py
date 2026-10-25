#!/usr/bin/env python3
"""Generate a reviewable AWS CloudFormation template. Does not call AWS."""
import json
from pathlib import Path
R={}
def ref(name): return {'Ref':name}
def attr(name,key): return {'Fn::GetAtt':[name,key]}
def sub(value): return {'Fn::Sub':value}
def join(values): return {'Fn::Join':['',values]}
def resource(name,kind,properties,**extras): R[name]={'Type':'AWS::'+kind,'Properties':properties,**extras}
def env(name,value): return {'Name':name,'Value':value}
def secret(name,value): return {'Name':name,'ValueFrom':value}

resource('Vpc','EC2::VPC',{'CidrBlock':'10.74.0.0/16','EnableDnsSupport':True,'EnableDnsHostnames':True})
resource('InternetGateway','EC2::InternetGateway',{})
resource('GatewayAttachment','EC2::VPCGatewayAttachment',{'VpcId':ref('Vpc'),'InternetGatewayId':ref('InternetGateway')})
resource('PublicRoutes','EC2::RouteTable',{'VpcId':ref('Vpc')})
resource('InternetRoute','EC2::Route',{'RouteTableId':ref('PublicRoutes'),'DestinationCidrBlock':'0.0.0.0/0','GatewayId':ref('InternetGateway')},DependsOn='GatewayAttachment')
for i in (1,2):
    resource(f'PublicSubnet{i}','EC2::Subnet',{'VpcId':ref('Vpc'),'CidrBlock':f'10.74.{i}.0/24','AvailabilityZone':{'Fn::Select':[i-1,{'Fn::GetAZs':''}]},'MapPublicIpOnLaunch':False})
    resource(f'PublicAssociation{i}','EC2::SubnetRouteTableAssociation',{'RouteTableId':ref('PublicRoutes'),'SubnetId':ref(f'PublicSubnet{i}')})
    resource(f'PrivateSubnet{i}','EC2::Subnet',{'VpcId':ref('Vpc'),'CidrBlock':f'10.74.{10+i}.0/24','AvailabilityZone':{'Fn::Select':[i-1,{'Fn::GetAZs':''}]},'MapPublicIpOnLaunch':False})
    resource(f'PrivateRoutes{i}','EC2::RouteTable',{'VpcId':ref('Vpc')})
    resource(f'PrivateAssociation{i}','EC2::SubnetRouteTableAssociation',{'RouteTableId':ref(f'PrivateRoutes{i}'),'SubnetId':ref(f'PrivateSubnet{i}')})
resource('NatAddress','EC2::EIP',{'Domain':'vpc'},DependsOn='GatewayAttachment')
resource('Nat','EC2::NatGateway',{'AllocationId':attr('NatAddress','AllocationId'),'SubnetId':ref('PublicSubnet1')})
for i in (1,2): resource(f'NatRoute{i}','EC2::Route',{'RouteTableId':ref(f'PrivateRoutes{i}'),'DestinationCidrBlock':'0.0.0.0/0','NatGatewayId':ref('Nat')})
resource('AlbSecurity','EC2::SecurityGroup',{'GroupDescription':'Public HTTPS and redirect only','VpcId':ref('Vpc'),'SecurityGroupIngress':[{'IpProtocol':'tcp','FromPort':p,'ToPort':p,'CidrIp':'0.0.0.0/0'} for p in (80,443)]})
resource('TaskSecurity','EC2::SecurityGroup',{'GroupDescription':'Application accepts traffic only from ALB','VpcId':ref('Vpc'),'SecurityGroupIngress':[{'IpProtocol':'tcp','FromPort':p,'ToPort':p,'SourceSecurityGroupId':ref('AlbSecurity')} for p in (3000,8000)]})
resource('DatabaseSecurity','EC2::SecurityGroup',{'GroupDescription':'PostgreSQL only from application tasks','VpcId':ref('Vpc'),'SecurityGroupIngress':[{'IpProtocol':'tcp','FromPort':5432,'ToPort':5432,'SourceSecurityGroupId':ref('TaskSecurity')}]})
resource('StorageKey','KMS::Key',{'Description':'Docket private storage encryption','EnableKeyRotation':True,'KeyPolicy':{'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'AWS':sub('arn:${AWS::Partition}:iam::${AWS::AccountId}:root')},'Action':'kms:*','Resource':'*'}]}},DeletionPolicy='Retain',UpdateReplacePolicy='Retain')
resource('Files','S3::Bucket',{'PublicAccessBlockConfiguration':{'BlockPublicAcls':True,'IgnorePublicAcls':True,'BlockPublicPolicy':True,'RestrictPublicBuckets':True},'OwnershipControls':{'Rules':[{'ObjectOwnership':'BucketOwnerEnforced'}]},'BucketEncryption':{'ServerSideEncryptionConfiguration':[{'ServerSideEncryptionByDefault':{'SSEAlgorithm':'aws:kms','KMSMasterKeyID':attr('StorageKey','Arn')},'BucketKeyEnabled':True}]},'VersioningConfiguration':{'Status':'Enabled'},'LifecycleConfiguration':{'Rules':[{'Id':'ExpireOldVersions','Status':'Enabled','NoncurrentVersionExpiration':{'NoncurrentDays':30},'AbortIncompleteMultipartUpload':{'DaysAfterInitiation':1}}]}},DeletionPolicy='Retain',UpdateReplacePolicy='Retain')
resource('FilePolicy','S3::BucketPolicy',{'Bucket':ref('Files'),'PolicyDocument':{'Version':'2012-10-17','Statement':[{'Effect':'Deny','Principal':'*','Action':'s3:*','Resource':[attr('Files','Arn'),join([attr('Files','Arn'),'/*'])],'Condition':{'Bool':{'aws:SecureTransport':'false'}}}]}})
resource('DatabaseSubnets','RDS::DBSubnetGroup',{'DBSubnetGroupDescription':'Private database subnets','SubnetIds':[ref('PrivateSubnet1'),ref('PrivateSubnet2')]})
resource('Database','RDS::DBInstance',{'Engine':'postgres','DBInstanceClass':ref('DatabaseClass'),'AllocatedStorage':'20','MaxAllocatedStorage':100,'StorageType':'gp3','StorageEncrypted':True,'KmsKeyId':attr('StorageKey','Arn'),'DBName':'docket','MasterUsername':'docket_admin','ManageMasterUserPassword':True,'DBSubnetGroupName':ref('DatabaseSubnets'),'VPCSecurityGroups':[ref('DatabaseSecurity')],'PubliclyAccessible':False,'BackupRetentionPeriod':14,'DeletionProtection':True,'AutoMinorVersionUpgrade':True,'MultiAZ':{'Fn::Equals':[ref('DatabaseMultiAZ'),'true']}},DeletionPolicy='Snapshot',UpdateReplacePolicy='Snapshot')
# CloudFormation property booleans use a named condition rather than an inline condition expression.
R['Database']['Properties']['MultiAZ']={'Fn::If':['MultiAZ',True,False]}
resource('ApplicationDbSecret','SecretsManager::Secret',{'Description':'Docket restricted application role; initialize with bootstrap task','GenerateSecretString':{'SecretStringTemplate':'{"username":"docket_app"}','GenerateStringKey':'password','PasswordLength':48,'ExcludePunctuation':True}},DeletionPolicy='Retain',UpdateReplacePolicy='Retain')
resource('DataSecret','SecretsManager::Secret',{'Description':'Persistent random application encryption material; preserve with backups','GenerateSecretString':{'PasswordLength':64,'ExcludePunctuation':True}},DeletionPolicy='Retain',UpdateReplacePolicy='Retain')
resource('ApiRepository','ECR::Repository',{'ImageScanningConfiguration':{'ScanOnPush':True},'ImageTagMutability':'IMMUTABLE','EncryptionConfiguration':{'EncryptionType':'AES256'}})
resource('WebRepository','ECR::Repository',{'ImageScanningConfiguration':{'ScanOnPush':True},'ImageTagMutability':'IMMUTABLE','EncryptionConfiguration':{'EncryptionType':'AES256'}})
resource('Logs','Logs::LogGroup',{'RetentionInDays':30})
resource('Cluster','ECS::Cluster',{'ClusterSettings':[{'Name':'containerInsights','Value':'enabled'}]})
trust={'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'ecs-tasks.amazonaws.com'},'Action':'sts:AssumeRole'}]}
resource('ExecutionRole','IAM::Role',{'AssumeRolePolicyDocument':trust,'ManagedPolicyArns':[sub('arn:${AWS::Partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy')],'Policies':[{'PolicyName':'InjectAppSecrets','PolicyDocument':{'Version':'2012-10-17','Statement':[{'Effect':'Allow','Action':['secretsmanager:GetSecretValue'],'Resource':[ref('ApplicationDbSecret'),ref('DataSecret'),{'Fn::If':['HasGeminiSecret',ref('GeminiSecretArn'),ref('AWS::NoValue')]}]}]}}]})
resource('BootstrapExecutionRole','IAM::Role',{'AssumeRolePolicyDocument':trust,'ManagedPolicyArns':[sub('arn:${AWS::Partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy')],'Policies':[{'PolicyName':'InitializeDatabaseOnly','PolicyDocument':{'Version':'2012-10-17','Statement':[{'Effect':'Allow','Action':['secretsmanager:GetSecretValue'],'Resource':[ref('ApplicationDbSecret'),attr('Database','MasterUserSecret.SecretArn')]}]}}]})
resource('TaskRole','IAM::Role',{'AssumeRolePolicyDocument':trust,'Policies':[{'PolicyName':'PrivateFilesAndSes','PolicyDocument':{'Version':'2012-10-17','Statement':[{'Effect':'Allow','Action':['s3:GetObject','s3:PutObject','s3:DeleteObject'],'Resource':join([attr('Files','Arn'),'/private/*'])},{'Effect':'Allow','Action':['kms:Encrypt','kms:Decrypt','kms:GenerateDataKey','kms:DescribeKey'],'Resource':attr('StorageKey','Arn')},{'Effect':'Allow','Action':['ses:SendEmail','ses:SendRawEmail'],'Resource':[sub('arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:identity/${EmailDomain}'),sub('arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:configuration-set/${MailConfiguration}')]},{'Effect':'Allow','Action':['textract:DetectDocumentText'],'Resource':'*'},{'Effect':'Allow','Action':'cloudwatch:PutMetricData','Resource':'*','Condition':{'StringEquals':{'cloudwatch:namespace':'Docket/Pilot'}}}]}}]})
resource('MailConfiguration','SES::ConfigurationSet',{'ReputationOptions':{'ReputationMetricsEnabled':True},'SuppressionOptions':{'SuppressedReasons':['BOUNCE','COMPLAINT']}})
resource('MailIdentity','SES::EmailIdentity',{'EmailIdentity':ref('EmailDomain'),'ConfigurationSetAttributes':{'ConfigurationSetName':ref('MailConfiguration')},'DkimSigningAttributes':{'NextSigningKeyLength':'RSA_2048_BIT'}})
for i in (1,2,3): resource(f'Dkim{i}','Route53::RecordSet',{'HostedZoneId':ref('HostedZoneId'),'Name':attr('MailIdentity',f'DkimDNSTokenName{i}'),'Type':'CNAME','TTL':'300','ResourceRecords':[attr('MailIdentity',f'DkimDNSTokenValue{i}')]})
resource('Certificate','CertificateManager::Certificate',{'DomainName':ref('DomainName'),'ValidationMethod':'DNS','DomainValidationOptions':[{'DomainName':ref('DomainName'),'HostedZoneId':ref('HostedZoneId')}]})
resource('LoadBalancer','ElasticLoadBalancingV2::LoadBalancer',{'Type':'application','Scheme':'internet-facing','Subnets':[ref('PublicSubnet1'),ref('PublicSubnet2')],'SecurityGroups':[ref('AlbSecurity')],'LoadBalancerAttributes':[{'Key':'routing.http.drop_invalid_header_fields.enabled','Value':'true'}]},DependsOn='GatewayAttachment')
for name,port,path in [('ApiTarget',8000,'/api/ready'),('WebTarget',3000,'/')]: resource(name,'ElasticLoadBalancingV2::TargetGroup',{'VpcId':ref('Vpc'),'TargetType':'ip','Protocol':'HTTP','Port':port,'HealthCheckPath':path,'HealthCheckIntervalSeconds':30,'HealthyThresholdCount':2,'UnhealthyThresholdCount':3})
resource('HttpsListener','ElasticLoadBalancingV2::Listener',{'LoadBalancerArn':ref('LoadBalancer'),'Port':443,'Protocol':'HTTPS','SslPolicy':'ELBSecurityPolicy-TLS13-1-2-2021-06','Certificates':[{'CertificateArn':ref('Certificate')}],'DefaultActions':[{'Type':'forward','TargetGroupArn':ref('WebTarget')}]})
resource('HttpListener','ElasticLoadBalancingV2::Listener',{'LoadBalancerArn':ref('LoadBalancer'),'Port':80,'Protocol':'HTTP','DefaultActions':[{'Type':'redirect','RedirectConfig':{'Protocol':'HTTPS','Port':'443','StatusCode':'HTTP_301'}}]})
resource('ApiRoute','ElasticLoadBalancingV2::ListenerRule',{'ListenerArn':ref('HttpsListener'),'Priority':1,'Conditions':[{'Field':'path-pattern','Values':['/api/*']}],'Actions':[{'Type':'forward','TargetGroupArn':ref('ApiTarget')}]})
resource('Dns','Route53::RecordSet',{'HostedZoneId':ref('HostedZoneId'),'Name':ref('DomainName'),'Type':'A','AliasTarget':{'DNSName':attr('LoadBalancer','DNSName'),'HostedZoneId':attr('LoadBalancer','CanonicalHostedZoneID')}})
common=[env('DOCKET_ENV','production'),env('DOCKET_DEMO_MODE','0'),env('PUBLIC_URL',sub('https://${DomainName}')),env('ALLOWED_ORIGINS',sub('https://${DomainName}')),env('DB_HOST',attr('Database','Endpoint.Address')),env('DB_USER','docket_app'),env('DB_NAME','docket'),env('MAIL_TRANSPORT','ses'),env('MAIL_FROM',ref('SenderEmail')),env('SUPPORT_EMAIL',ref('SupportEmail')),env('SES_CONFIGURATION_SET',ref('MailConfiguration')),env('AWS_REGION',ref('AWS::Region')),env('OBJECT_BUCKET',ref('Files')),env('OBJECT_KMS_KEY_ID',attr('StorageKey','Arn')),env('CLAMAV_HOST','127.0.0.1'),env('METRICS_NAMESPACE','Docket/Pilot'),env('OCR_PROVIDER','gemini')]
secrets=[secret('DB_PASSWORD',join([ref('ApplicationDbSecret'),':password::'])),secret('DATA_ENCRYPTION_SECRET',ref('DataSecret')),{'Fn::If':['HasGeminiSecret',secret('GEMINI_API_KEY',ref('GeminiSecretArn')),ref('AWS::NoValue')]}]
def log(name): return {'LogDriver':'awslogs','Options':{'awslogs-group':ref('Logs'),'awslogs-region':ref('AWS::Region'),'awslogs-stream-prefix':name}}
base={'RequiresCompatibilities':['FARGATE'],'NetworkMode':'awsvpc','Cpu':'2048','Memory':'6144','ExecutionRoleArn':attr('ExecutionRole','Arn'),'TaskRoleArn':attr('TaskRole','Arn'),'RuntimePlatform':{'CpuArchitecture':'X86_64','OperatingSystemFamily':'LINUX'}}
containers=[{'Name':'api','Image':ref('ApiImageUri'),'Essential':True,'PortMappings':[{'ContainerPort':8000}],'Environment':common,'Secrets':secrets,'LogConfiguration':log('api'),'ReadonlyRootFilesystem':True,'MountPoints':[{'SourceVolume':'temporary','ContainerPath':'/tmp'}]}, {'Name':'worker','Image':ref('ApiImageUri'),'Command':['python','-m','app.workers.delivery'],'Essential':True,'Environment':common,'Secrets':secrets,'LogConfiguration':log('worker'),'ReadonlyRootFilesystem':True}, {'Name':'web','Image':ref('WebImageUri'),'Essential':True,'PortMappings':[{'ContainerPort':3000}],'LogConfiguration':log('web')}, {'Name':'clamav','Image':ref('ClamavImageUri'),'Essential':True,'MemoryReservation':3072,'LogConfiguration':log('scanner')}]
containers[0]['DependsOn']=[{'ContainerName':'init-storage','Condition':'SUCCESS'}]
containers.append({'Name':'init-storage','Image':ref('ApiImageUri'),'Essential':False,'User':'0','Command':['python','-c',"import os; os.chmod('/work',0o1777)"],'MountPoints':[{'SourceVolume':'temporary','ContainerPath':'/work'}],'LogConfiguration':log('init'),'ReadonlyRootFilesystem':True})
resource('Task','ECS::TaskDefinition',base|{'ContainerDefinitions':containers,'Volumes':[{'Name':'temporary'}]})
bootstrap=base|{'Cpu':'512','Memory':'1024','ExecutionRoleArn':attr('BootstrapExecutionRole','Arn'),'ContainerDefinitions':[{'Name':'bootstrap','Image':ref('ApiImageUri'),'Essential':True,'Command':['python','-m','app.bootstrap_database'],'Environment':[env('DB_HOST',attr('Database','Endpoint.Address')),env('DB_NAME','docket'),env('DB_USER','docket_app')],'Secrets':[secret('DB_PASSWORD',join([ref('ApplicationDbSecret'),':password::'])),secret('BOOTSTRAP_PASSWORD',join([attr('Database','MasterUserSecret.SecretArn'),':password::']))],'LogConfiguration':log('bootstrap')}]}
resource('BootstrapTask','ECS::TaskDefinition',bootstrap)
resource('Service','ECS::Service',{'Cluster':ref('Cluster'),'LaunchType':'FARGATE','PlatformVersion':'1.4.0','TaskDefinition':ref('Task'),'DesiredCount':ref('DesiredCount'),'DeploymentConfiguration':{'DeploymentCircuitBreaker':{'Enable':True,'Rollback':True}},'HealthCheckGracePeriodSeconds':600,'NetworkConfiguration':{'AwsvpcConfiguration':{'AssignPublicIp':'DISABLED','Subnets':[ref('PrivateSubnet1'),ref('PrivateSubnet2')],'SecurityGroups':[ref('TaskSecurity')]}},'LoadBalancers':[{'ContainerName':'api','ContainerPort':8000,'TargetGroupArn':ref('ApiTarget')},{'ContainerName':'web','ContainerPort':3000,'TargetGroupArn':ref('WebTarget')}]},DependsOn=['HttpsListener','ApiRoute','NatRoute1','NatRoute2'])
resource('Firewall','WAFv2::WebACL',{'Scope':'REGIONAL','DefaultAction':{'Allow':{}},'VisibilityConfig':{'CloudWatchMetricsEnabled':True,'SampledRequestsEnabled':False,'MetricName':'DocketFirewall'},'Rules':[{'Name':'RequestRate','Priority':0,'Action':{'Block':{}},'Statement':{'RateBasedStatement':{'Limit':1000,'AggregateKeyType':'IP'}},'VisibilityConfig':{'CloudWatchMetricsEnabled':True,'SampledRequestsEnabled':False,'MetricName':'DocketRateLimit'}}]})
resource('FirewallAssociation','WAFv2::WebACLAssociation',{'ResourceArn':ref('LoadBalancer'),'WebACLArn':attr('Firewall','Arn')})
resource('Alerts','SNS::Topic',{'DisplayName':'Docket pilot infrastructure alerts'})
resource('AlertSubscription','SNS::Subscription',{'TopicArn':ref('Alerts'),'Protocol':'email','Endpoint':ref('AlertEmail')},Condition='HasAlertEmail')
for name,namespace,metric,threshold,period,comparison,dimensions,missing in [
 ('ApiErrors','AWS/ApplicationELB','HTTPCode_Target_5XX_Count',5,60,'GreaterThanThreshold',[{'Name':'LoadBalancer','Value':attr('LoadBalancer','LoadBalancerFullName')}],'notBreaching'),
 ('WorkerMissing','Docket/Pilot','WorkerAlive',1,60,'LessThanThreshold',[],'breaching'),
 ('DeliveryFailures','Docket/Pilot','FailedReminders',0,60,'GreaterThanThreshold',[],'notBreaching'),
 ('DbStorage','AWS/RDS','FreeStorageSpace',2147483648,300,'LessThanThreshold',[{'Name':'DBInstanceIdentifier','Value':ref('Database')}],'missing')]:
 resource(name,'CloudWatch::Alarm',{'Namespace':namespace,'MetricName':metric,'Dimensions':dimensions,'Statistic':'Maximum','Period':period,'EvaluationPeriods':3,'Threshold':threshold,'ComparisonOperator':comparison,'TreatMissingData':missing,'AlarmActions':[ref('Alerts')]})
params={
 'DomainName':{'Type':'String','Description':'Owned app hostname, e.g. app.example.in'},
 'EmailDomain':{'Type':'String','Description':'SES sender domain in the supplied Route53 zone'},
 'HostedZoneId':{'Type':'AWS::Route53::HostedZone::Id'},
 'SenderEmail':{'Type':'String','Description':'Sender address under the SES identity domain'},
 'SupportEmail':{'Type':'String'},
 'AlertEmail':{'Type':'String','Default':'','Description':'Optional infrastructure alert subscriber; owner must confirm subscription'},
 'ApiImageUri':{'Type':'String','Description':'API ECR image URI pinned to immutable tag or digest'},
 'WebImageUri':{'Type':'String','Description':'Web ECR image URI pinned to immutable tag or digest'},
 'ClamavImageUri':{'Type':'String','Default':'clamav/clamav:stable','Description':'Use a reviewed pinned image digest for deployment'},
 'GeminiSecretArn':{'Type':'String','Default':'','Description':'Optional Secrets Manager ARN containing the Gemini API key; original image OCR still requires business-owner opt-in'},
 'DesiredCount':{'Type':'Number','Default':0,'MinValue':0,'MaxValue':4,'Description':'Keep 0 until images and restricted DB role are initialized'},
 'DatabaseClass':{'Type':'String','Default':'db.t4g.micro','AllowedValues':['db.t4g.micro','db.t4g.small','db.t4g.medium']},
 'DatabaseMultiAZ':{'Type':'String','Default':'false','AllowedValues':['true','false'],'Description':'Enable for production availability; increases cost'},
}
template={'AWSTemplateFormatVersion':'2010-09-09','Description':'Docket AWS pilot: paid infrastructure, review before executing; initial app service count is zero.','Parameters':params,'Conditions':{'HasGeminiSecret':{'Fn::Not':[{'Fn::Equals':[ref('GeminiSecretArn'),'']}]},'MultiAZ':{'Fn::Equals':[ref('DatabaseMultiAZ'),'true']},'HasAlertEmail':{'Fn::Not':[{'Fn::Equals':[ref('AlertEmail'),'']}]}},'Resources':R,'Outputs':{name:{'Value':value} for name,value in {'Url':sub('https://${DomainName}'),'ApiRepository':attr('ApiRepository','RepositoryUri'),'WebRepository':attr('WebRepository','RepositoryUri'),'Cluster':ref('Cluster'),'Service':attr('Service','Name'),'BootstrapTask':ref('BootstrapTask'),'PrivateSubnet1':ref('PrivateSubnet1'),'PrivateSubnet2':ref('PrivateSubnet2'),'TaskSecurityGroup':ref('TaskSecurity'),'FilesBucket':ref('Files'),'LogGroup':ref('Logs'),'AlertsTopic':ref('Alerts')}.items()}}
path=Path(__file__).resolve().parents[1]/'deploy/aws/cloudformation.json'
path.write_text(json.dumps(template,indent=2)+'\n')
print(f'Generated {path.name}: {len(R)} resources. No AWS calls or charges incurred.')
