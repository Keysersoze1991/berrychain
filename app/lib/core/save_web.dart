import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

/// In the browser: a download of the bytes under the parcel's name.
Future<void> saveBytes(String name, Uint8List bytes) async {
  final safe = name.replaceAll(RegExp(r'[^\w.\- ]'), '_');
  final blob = web.Blob([bytes.toJS].toJS, web.BlobPropertyBag(type: 'application/octet-stream'));
  final url = web.URL.createObjectURL(blob);
  final a = web.HTMLAnchorElement()
    ..href = url
    ..download = safe
    ..style.display = 'none';
  web.document.body!.append(a);
  a.click();
  a.remove();
  web.URL.revokeObjectURL(url);
}
