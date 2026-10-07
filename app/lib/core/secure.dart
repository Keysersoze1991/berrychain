// Small defences around the two places the app shows or copies secrets: the
// twelve words and the sealed chest file. All of it goes over one platform
// channel, berrychain/secure, implemented in MainActivity.kt and
// AppDelegate.swift; no third-party plugin.
//
//   copySensitive  puts text on the clipboard marked sensitive (Android 13+
//                  keeps it out of the clipboard preview and sync), gives it
//                  an expiry on iOS, and on Android clears it after [ttl] if
//                  it is still there. Browsers get a plain copy; they offer
//                  neither a silent read-back nor an expiry.
//   protectScreen  Android: FLAG_SECURE while on, so screenshots, screen
//                  recording and the recents thumbnail are black.
//                  iOS cannot refuse a screenshot; it hides the content while
//                  the screen is being recorded or mirrored, and reports a
//                  screenshot the moment it happens so the screen can react
//                  (see [onScreenshot]).
//   onScreenshot   a callback for that report; the words screen uses it to
//                  close and warn.
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

const _channel = MethodChannel('berrychain/secure');
void Function()? onScreenshot;
bool _listening = false;

bool get _isMobile =>
    !kIsWeb && (defaultTargetPlatform == TargetPlatform.android || defaultTargetPlatform == TargetPlatform.iOS);

void _listen() {
  if (_listening || !_isMobile) return;
  _listening = true;
  _channel.setMethodCallHandler((call) async {
    if (call.method == 'screenshotTaken') onScreenshot?.call();
  });
}

/// Copies [text] as a sensitive clip. Returns true when the platform gave it
/// an expiry itself (iOS); the caller can word its toast accordingly.
Future<bool> copySensitive(String text, {Duration ttl = const Duration(seconds: 60)}) async {
  var expires = false;
  var native = false;
  if (_isMobile) {
    try {
      final r = await _channel.invokeMethod<String>('copySensitive', {'text': text, 'ttl': ttl.inSeconds});
      native = r != null;
      expires = r == 'expires';
    } catch (_) {
      native = false;
    }
  }
  if (!native) await Clipboard.setData(ClipboardData(text: text));
  if (kIsWeb || expires) return expires;
  // Clear it ourselves after the ttl, but only if it is still our text, so a
  // later copy of something else is left alone.
  Timer(ttl, () async {
    try {
      final now = await Clipboard.getData(Clipboard.kTextPlain);
      if (now?.text == text) await Clipboard.setData(const ClipboardData(text: ' '));
    } catch (_) {}
  });
  return false;
}

Future<void> protectScreen(bool on) async {
  if (!_isMobile) return;
  _listen();
  try {
    await _channel.invokeMethod<void>('protect', {'on': on});
  } catch (_) {}
}
