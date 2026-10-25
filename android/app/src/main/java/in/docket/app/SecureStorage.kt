package `in`.docket.app

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import android.util.Base64
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONObject

/** AES-GCM files with a non-exportable Android Keystore key. No plaintext fallback. */
class LocalVault(private val context: Context) {
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("docket-storage-v1", null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("docket-storage-v1", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setRandomizedEncryptionRequired(true).build())
        }.generateKey()
    }
    fun encrypt(bytes: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key())
        return "DKT1".toByteArray() + cipher.iv + cipher.doFinal(bytes)
    }
    fun decrypt(bytes: ByteArray): ByteArray {
        require(bytes.size > 32 && String(bytes.copyOfRange(0, 4)) == "DKT1") { "Encrypted storage could not be opened. Sign in again or restore your original documents." }
        return Cipher.getInstance("AES/GCM/NoPadding").run { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(4, 16))); doFinal(bytes.copyOfRange(16, bytes.size)) }
    }
    @Synchronized fun write(name: String, bytes: ByteArray) {
        val file = AtomicFile(File(context.filesDir, name)); val stream = file.startWrite()
        try { stream.write(encrypt(bytes)); file.finishWrite(stream) } catch (e: Exception) { file.failWrite(stream); throw e }
    }
    fun read(name: String): ByteArray? = File(context.filesDir, name).takeIf { it.exists() }?.let { decrypt(AtomicFile(it).openRead().use { stream -> stream.readBytes() }) }
}

class AccountSession(private val context: Context) {
    private val vault = LocalVault(context)
    var value: JSONObject? = runCatching { vault.read("session.enc")?.let { JSONObject(String(it)) } }.getOrNull()
        private set
    val token get() = value?.text("access_token").orEmpty()
    val workspace get() = value?.text("workspace_id").orEmpty()
    val role get() = value?.text("role", "owner").orEmpty()
    fun save(json: JSONObject) { vault.write("session.enc", json.toString().toByteArray()); value = json }
    fun clear() { value = null; File(context.filesDir, "session.enc").delete(); File(context.filesDir, "api-cache.enc").delete(); File(context.filesDir, "api-cache.json").delete() }
}
