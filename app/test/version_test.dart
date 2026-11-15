import 'dart:io';

import 'package:berrychain_app/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  // The version shown in Settings and on the welcome screen sat at 0.15.0 through three releases.
  test('the version the app shows is the version it is built as', () {
    final line = File('pubspec.yaml').readAsLinesSync().firstWhere((l) => l.startsWith('version: '));
    expect(line.substring('version: '.length).split('+').first, appVersion);
  });
}
