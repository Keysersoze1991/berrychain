package link.berrychain.berrychain_app

import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import android.os.PersistableBundle
import android.view.WindowManager
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

// FlutterFragmentActivity rather than FlutterActivity: the biometric prompt
// (local_auth) needs a FragmentActivity to attach to.
class MainActivity : FlutterFragmentActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "berrychain/secure").setMethodCallHandler { call, result ->
            when (call.method) {
                // A clipboard entry flagged sensitive: Android 13+ keeps it out of the
                // clipboard preview and cross-device sync. Dart clears it after the ttl.
                "copySensitive" -> {
                    val text = call.argument<String>("text") ?: ""
                    val clip = ClipData.newPlainText("BerryChain", text)
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        clip.description.extras = PersistableBundle().apply {
                            putBoolean(ClipDescription.EXTRA_IS_SENSITIVE, true)
                        }
                    }
                    (getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(clip)
                    result.success("copied")
                }
                // FLAG_SECURE while the recovery words are on screen: screenshots,
                // screen recording and the recents thumbnail come out black.
                "protect" -> {
                    val on = call.argument<Boolean>("on") ?: false
                    if (on) window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
                    else window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }
}
