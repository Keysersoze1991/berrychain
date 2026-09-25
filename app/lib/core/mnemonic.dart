import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as c;
import 'package:cryptography/cryptography.dart';

import 'crypto.dart';
import 'wordlist_en.dart';

/// Twelve-word recovery phrases, BIP-39 encoding and seed, from which both
/// wallet keys are drawn with HKDF-SHA256. Byte-for-byte the reference
/// implementation in berrychain/mnemonic.py.

final Map<String, int> _index = {for (var i = 0; i < bip39English.length; i++) bip39English[i]: i};

String newPhrase([Uint8List? entropy]) {
  final ent = entropy ?? randomBytes(16);
  if (ent.length != 16) throw ArgumentError('entropy must be 16 bytes');
  final bits = StringBuffer();
  for (final b in ent) {
    bits.write(b.toRadixString(2).padLeft(8, '0'));
  }
  final check = c.sha256.convert(ent).bytes[0].toRadixString(2).padLeft(8, '0').substring(0, 4);
  final all = bits.toString() + check;
  final words = <String>[];
  for (var i = 0; i < 132; i += 11) {
    words.add(bip39English[int.parse(all.substring(i, i + 11), radix: 2)]);
  }
  return words.join(' ');
}

String normalizePhrase(String phrase) => phrase.toLowerCase().trim().split(RegExp(r'\s+')).where((w) => w.isNotEmpty).join(' ');

/// The normalized phrase, or a [FormatException] with a plain reason.
String validatePhrase(String phrase) {
  final words = normalizePhrase(phrase).split(' ');
  if (words.length != 12) throw FormatException('a recovery phrase has 12 words, this has ${words.length}');
  final bad = words.where((w) => !_index.containsKey(w)).toList();
  if (bad.isNotEmpty) throw FormatException('not in the word list: ${bad.take(3).join(', ')}');
  final bits = words.map((w) => _index[w]!.toRadixString(2).padLeft(11, '0')).join();
  final ent = Uint8List(16);
  for (var i = 0; i < 16; i++) {
    ent[i] = int.parse(bits.substring(i * 8, i * 8 + 8), radix: 2);
  }
  final check = c.sha256.convert(ent).bytes[0].toRadixString(2).padLeft(8, '0').substring(0, 4);
  if (bits.substring(128) != check) throw const FormatException('the words do not check out; one is probably wrong or out of order');
  return words.join(' ');
}

Future<Uint8List> seedFromPhrase(String phrase) async {
  final words = validatePhrase(phrase);
  final pbkdf2 = Pbkdf2(macAlgorithm: Hmac.sha512(), iterations: 2048, bits: 512);
  final key = await pbkdf2.deriveKey(secretKey: SecretKey(utf8.encode(words)), nonce: utf8.encode('mnemonic'));
  return Uint8List.fromList(await key.extractBytes());
}

Future<Uint8List> _hkdf(List<int> seed, String info) async {
  final k = await Hkdf(hmac: Hmac.sha256(), outputLength: 32).deriveKey(secretKey: SecretKey(seed), nonce: const [], info: utf8.encode(info));
  return Uint8List.fromList(await k.extractBytes());
}

/// (signPrivHex, encPrivHex) for a phrase.
Future<(String, String)> keysFromPhrase(String phrase) async {
  final seed = await seedFromPhrase(phrase);
  return (toHex(await _hkdf(seed, 'berry-sign-v1')), toHex(await _hkdf(seed, 'berry-enc-v1')));
}
