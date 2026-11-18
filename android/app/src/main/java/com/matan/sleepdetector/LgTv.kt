package com.matan.sleepdetector

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/**
 * Minimal LG webOS (SSAP) client over the LAN. Talks directly from the phone to the TV.
 * Tries ws://ip:3000 first, then wss://ip:3001 (self-signed cert, accepted for this LAN host only).
 */
class LgTv(private val ip: String, private var clientKey: String?, private val onNewKey: (String) -> Unit) {

    data class Result(val ok: Boolean, val message: String)

    private val plain = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)
        .build()

    private val insecure: OkHttpClient by lazy {
        val tm = object : X509TrustManager {
            override fun checkClientTrusted(c: Array<X509Certificate>, a: String) {}
            override fun checkServerTrusted(c: Array<X509Certificate>, a: String) {}
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }
        val ctx = SSLContext.getInstance("TLS").apply { init(null, arrayOf(tm), SecureRandom()) }
        plain.newBuilder()
            .sslSocketFactory(ctx.socketFactory, tm)
            .hostnameVerifier { host, _ -> host == ip }
            .build()
    }

    /** Registers (prompting on the TV the first time) and stores the client key. */
    fun pair(): Result = run(null, waitSeconds = 60)

    fun powerOff(): Result = run("ssap://system/turnOff", waitSeconds = 20)

    private fun run(uri: String?, waitSeconds: Long): Result {
        val first = attempt("ws://$ip:3000", plain, uri, waitSeconds)
        if (first.ok || !first.message.startsWith("connect")) return first
        return attempt("wss://$ip:3001", insecure, uri, waitSeconds)
    }

    private fun attempt(url: String, client: OkHttpClient, uri: String?, waitSeconds: Long): Result {
        val latch = CountDownLatch(1)
        var result = Result(false, "timeout (did you accept the prompt on the TV?)")
        val ws = client.newWebSocket(Request.Builder().url(url).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                webSocket.send(registerMessage())
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val msg = try { JSONObject(text) } catch (e: Exception) { return }
                when (msg.optString("type")) {
                    "registered" -> {
                        val key = msg.optJSONObject("payload")?.optString("client-key")
                        if (!key.isNullOrEmpty()) {
                            clientKey = key
                            onNewKey(key)
                        }
                        if (uri == null) {
                            result = Result(true, "paired")
                            latch.countDown()
                        } else {
                            webSocket.send(JSONObject()
                                .put("type", "request").put("id", "cmd_1").put("uri", uri).toString())
                        }
                    }
                    "response" -> if (msg.optString("id") == "cmd_1") {
                        val ok = msg.optJSONObject("payload")?.optBoolean("returnValue", true) ?: true
                        result = Result(ok, if (ok) "sent" else "TV refused: $text")
                        latch.countDown()
                    }
                    "error" -> {
                        result = Result(false, "TV error: ${msg.optString("error")}")
                        latch.countDown()
                    }
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                result = Result(false, "connect failed ($url): ${t.message}")
                latch.countDown()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                latch.countDown()
            }
        })
        latch.await(waitSeconds, TimeUnit.SECONDS)
        ws.close(1000, null)
        return result
    }

    private fun registerMessage(): String {
        val perms = listOf(
            "LAUNCH", "LAUNCH_WEBAPP", "APP_TO_APP", "CONTROL_AUDIO", "CONTROL_POWER",
            "READ_INSTALLED_APPS", "READ_POWER_STATE", "READ_RUNNING_APPS", "READ_CURRENT_CHANNEL",
        )
        val payload = JSONObject()
            .put("forcePairing", false)
            .put("pairingType", "PROMPT")
            .put("manifest", JSONObject()
                .put("manifestVersion", 1)
                .put("appVersion", "1.0")
                .put("permissions", JSONArray(perms)))
        clientKey?.takeIf { it.isNotEmpty() }?.let { payload.put("client-key", it) }
        return JSONObject().put("type", "register").put("id", "register_0").put("payload", payload).toString()
    }
}
