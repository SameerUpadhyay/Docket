package `in`.docket.app

import java.net.ServerSocket
import java.net.InetAddress
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ApiClientTest {
    @Test fun credentialsAreScopedToOriginAndWorkspace() {
        val server = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))
        val headers = mutableMapOf<String, String>()
        var failure: Throwable? = null
        val worker = Thread {
            try { server.accept().use { socket ->
                val reader = socket.getInputStream().bufferedReader()
                var line = reader.readLine()
                while (line != null && line.isNotBlank()) {
                    if (line.contains(":")) headers[line.substringBefore(':').lowercase()] = line.substringAfter(':').trim()
                    line = reader.readLine()
                }
                val body = "{\"status\":\"ok\"}"
                socket.getOutputStream().write("HTTP/1.1 200 OK\r\nContent-Length: ${body.length}\r\nConnection: close\r\n\r\n$body".toByteArray())
            } } catch (e: Throwable) { failure = e }
        }
        worker.start()
        try {
            val result = ApiClient("http://127.0.0.1:${server.localPort}", "opaque-session", "business-1").json("/auth/me")
            worker.join(3000); failure?.let { throw AssertionError(it) }
            assertEquals("ok", JSONObject(result).getString("status"))
            assertEquals("Bearer opaque-session", headers["authorization"])
            assertEquals("business-1", headers["x-workspace-id"]); assertEquals("1", headers["x-docket-request"])
        } finally { server.close() }
    }
    @Test fun remoteHttpAndCredentialUrlsAreRejected() {
        for (origin in listOf("http://example.in", "https://user:password@example.in", "https://example.in/api", "https://example.in?token=secret")) {
            try { ApiClient(origin); fail("Unsafe origin was accepted") } catch (_: IllegalArgumentException) { }
        }
    }
}
