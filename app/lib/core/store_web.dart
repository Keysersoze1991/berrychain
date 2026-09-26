import 'package:web/web.dart' as web;

/// In the browser there is no documents directory; names are keys in
/// localStorage, prefixed so nothing else on the origin collides with them.
Future<String> storeDir() async => 'berrychain/';

Future<bool> existsText(String path) async => web.window.localStorage.getItem(path) != null;

Future<String?> readText(String path) async => web.window.localStorage.getItem(path);

Future<void> writeText(String path, String text) async => web.window.localStorage.setItem(path, text);
