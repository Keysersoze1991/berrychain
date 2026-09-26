import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// The directory that file names are joined to. The trailing separator is
/// included so callers can write `'${await storeDir()}wallet.json'`.
Future<String> storeDir() async => '${(await getApplicationDocumentsDirectory()).path}/';

Future<bool> existsText(String path) => File(path).exists();

Future<String?> readText(String path) async {
  final f = File(path);
  if (!await f.exists()) return null;
  return f.readAsString();
}

/// Writes to a temporary file and renames it over the target, so a crash
/// mid-write never leaves a half-written wallet.
Future<void> writeText(String path, String text) async {
  final tmp = File('$path.tmp');
  await tmp.writeAsString(text, flush: true);
  await tmp.rename(path);
}
