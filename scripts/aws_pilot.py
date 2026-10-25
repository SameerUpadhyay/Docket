#!/usr/bin/env python3
"""AWS pilot operations. Plan creates only a change set; execute is explicit.

Uses AWS profiles/SSO or workload credentials. Never accepts access keys on the
command line, prints secrets, or writes credentials to repository files.
"""
import argparse,base64,json,subprocess,sys,time,uuid
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--profile'); p.add_argument('--region',default='ap-south-1'); p.add_argument('--stack',default='docket-pilot')
sub=p.add_subparsers(dest='command',required=True)
plan=sub.add_parser('plan'); plan.add_argument('--parameters',required=True,type=Path)
execute=sub.add_parser('execute'); execute.add_argument('--change-set',required=True); execute.add_argument('--approve-paid-resources',action='store_true')
images=sub.add_parser('images'); images.add_argument('--tag',required=True)
sub.add_parser('bootstrap-database')
sub.add_parser('status')
args=p.parse_args()
session=boto3.Session(profile_name=args.profile,region_name=args.region)
cf=session.client('cloudformation')
def stack(): return cf.describe_stacks(StackName=args.stack)['Stacks'][0]
def outputs(): return {o['OutputKey']:o['OutputValue'] for o in stack().get('Outputs',[])}
if args.command=='plan':
    template=json.dumps(json.loads((root/'deploy/aws/cloudformation.json').read_text()),separators=(',',':'))
    parameters=json.loads(args.parameters.read_text())
    if any('REPLACE' in str(x) for x in parameters): p.error('Replace every parameter placeholder before creating a change set.')
    try: stack(); kind='UPDATE'
    except ClientError as e:
        if 'does not exist' not in str(e): raise
        kind='CREATE'
    result=cf.create_change_set(StackName=args.stack,ChangeSetName='review-'+uuid.uuid4().hex[:12],ChangeSetType=kind,TemplateBody=template,Parameters=parameters,Capabilities=['CAPABILITY_IAM'],Description='Review before execution: paid Docket AWS pilot infrastructure')
    print('Change set created; no infrastructure has been executed:',result['Id'])
    print('Inspect the change set and current AWS Pricing Calculator estimate before explicitly executing it.')
elif args.command=='execute':
    if not args.approve_paid_resources: p.error('Executing provisions billable resources. Review and supply --approve-paid-resources explicitly.')
    reviewed=cf.describe_change_set(ChangeSetName=args.change_set)
    if reviewed['StackName']!=args.stack: p.error('Change set does not belong to the selected stack.')
    if reviewed['Status']!='CREATE_COMPLETE': p.error('Change set is not ready to execute.')
    cf.execute_change_set(ChangeSetName=args.change_set)
    print('Execution started. Follow stack events; database, NAT, ALB, WAF and ECS can incur charges.')
elif args.command=='status':
    value=stack(); print('Stack:',value['StackStatus']); print(json.dumps(outputs(),indent=2))
elif args.command=='images':
    import re
    if not re.fullmatch('[A-Za-z0-9_.-]{1,100}',args.tag): p.error('Use a simple immutable image tag.')
    values=outputs(); ecr=session.client('ecr')
    login=ecr.get_authorization_token()['authorizationData'][0]
    username,password=base64.b64decode(login['authorizationToken']).decode().split(':',1)
    subprocess.run(['docker','login','--username',username,'--password-stdin',login['proxyEndpoint']],input=password.encode(),check=True,stdout=subprocess.DEVNULL)
    try:
        for folder,key in [('backend','ApiRepository'),('frontend','WebRepository')]:
            image=values[key]+':'+args.tag
            subprocess.run(['docker','buildx','build','--platform','linux/amd64','--push','-t',image,'-f',str(root/folder/'Dockerfile'),str(root/folder)],check=True)
            print(key+' image:',image)
    finally: subprocess.run(['docker','logout',login['proxyEndpoint']],stdout=subprocess.DEVNULL,check=False)
    print('Create a new change set with these image URIs, retaining DesiredCount=0 until database bootstrap succeeds.')
elif args.command=='bootstrap-database':
    values=outputs(); ecs=session.client('ecs')
    definition=ecs.describe_task_definition(taskDefinition=values['BootstrapTask'])['taskDefinition']
    if not definition['containerDefinitions'][0]['image'].startswith(values['ApiRepository']+':') and '@sha256:' not in definition['containerDefinitions'][0]['image']:
        p.error('Update the stack to the built API ECR image before bootstrapping.')
    result=ecs.run_task(cluster=values['Cluster'],taskDefinition=values['BootstrapTask'],launchType='FARGATE',platformVersion='1.4.0',count=1,networkConfiguration={'awsvpcConfiguration':{'subnets':[values['PrivateSubnet1'],values['PrivateSubnet2']],'securityGroups':[values['TaskSecurityGroup']],'assignPublicIp':'DISABLED'}})
    if result.get('failures'): raise SystemExit('Bootstrap task failed to start. Inspect the ECS service and redacted logs.')
    print('Bootstrap task started:',result['tasks'][0]['taskArn'])
    print('Wait for exit code 0 in ECS, then create an updated change set setting DesiredCount=1.')
