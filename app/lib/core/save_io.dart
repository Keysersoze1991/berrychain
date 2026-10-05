import 'dart:io';
import 'dart:typed_data';

import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

/// Writes the bytes to a temporary file and opens the system share sheet, so
/// the person picks where it goes (Files, Drive, another app). The temporary
/// copy is removed afterwards.
Future<void> saveBytes(String name, Uint8List bytes) async {
  final dir = await getTemporaryDirectory();
  final safe = name.replaceAll(RegExp(r'[^\w.\- ]'), '_');
  final f = File('${dir.path}${Platform.pathSeparator}$safe');
  await f.writeAsBytes(bytes, flush: true);
  try {
    await SharePlus.instance.share(ShareParams(files: [XFile(f.path)], subject: safe));
  } finally {
    try {
      await f.delete();
    } catch (_) {}
  }
}
