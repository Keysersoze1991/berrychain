import 'dart:typed_data';

import 'package:image/image.dart' as img;

/// Shrink a camera picture until it fits the letter budget: longest side at
/// most [maxSide] pixels, then JPEG quality stepped down until the encoded
/// size is under [maxBytes]. Pure Dart; run it off the UI thread.
Uint8List shrinkPhoto(Uint8List original, {int maxSide = 400, int maxBytes = 18 * 1024}) {
  var image = img.decodeImage(original);
  if (image == null) throw const FormatException('that picture could not be read');
  image = img.bakeOrientation(image);
  if (image.width > maxSide || image.height > maxSide) {
    image = image.width >= image.height ? img.copyResize(image, width: maxSide) : img.copyResize(image, height: maxSide);
  }
  for (var side = maxSide; side >= 120; side = side * 3 ~/ 4) {
    var work = image;
    if (work.width > side || work.height > side) {
      work = work.width >= work.height ? img.copyResize(work, width: side) : img.copyResize(work, height: side);
    }
    for (final q in [70, 60, 50, 40, 30]) {
      final out = Uint8List.fromList(img.encodeJpg(work, quality: q));
      if (out.length <= maxBytes) return out;
    }
  }
  throw const FormatException('the picture cannot be made small enough');
}

Map<String, dynamic> shrinkPhotoArgs(Uint8List bytes, int maxSide, int maxBytes) =>
    {'bytes': bytes, 'maxSide': maxSide, 'maxBytes': maxBytes};

/// Entry point for `compute`.
Uint8List shrinkPhotoInIsolate(Map<String, dynamic> a) =>
    shrinkPhoto(a['bytes'] as Uint8List, maxSide: a['maxSide'] as int, maxBytes: a['maxBytes'] as int);
