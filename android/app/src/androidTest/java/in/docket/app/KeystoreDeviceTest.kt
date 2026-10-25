package `in`.docket.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.security.KeyStore
import java.util.UUID

/** Device-only acceptance: never overwrites application records or deletes their key. */
@RunWith(AndroidJUnit4::class)
class KeystoreDeviceTest {
    @Test fun encryptedRoundTripSurvivesNewInstanceAndRejectsTampering() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val name = "device-check-${UUID.randomUUID()}.enc"
        val plaintext = "Synthetic account session for device verification only".toByteArray()
        try {
            LocalVault(context).write(name, plaintext)
            val disk = File(context.filesDir, name).readBytes()
            assertFalse(String(disk).contains("Synthetic account"))
            assertArrayEquals(plaintext, LocalVault(context).read(name))
            val changed = disk.copyOf(); changed[changed.lastIndex] = (changed.last().toInt() xor 1).toByte()
            try { LocalVault(context).decrypt(changed); fail("Modified ciphertext was accepted") } catch (_: javax.crypto.AEADBadTagException) { }
            val keys = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            assertNull(keys.getKey("docket-storage-v1", null).encoded)
        } finally { File(context.filesDir, name).delete(); File(context.filesDir, "$name.bak").delete() }
    }
}
