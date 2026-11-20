import 'dart:convert';
import 'dart:typed_data';

import 'package:berrychain_app/core/crypto.dart';
import 'package:berrychain_app/core/letters.dart';
import 'package:berrychain_app/core/parcels.dart';
import 'package:flutter_test/flutter_test.dart';

/// The fixes from the 20 November 2026 security review (0.16.4).
void main() {
  group('letters are padded to a size band (finding 8)', () {
    test('a short letter becomes exactly 512 bytes and still opens the same', () {
      final plain = composeLetter('Ahoy', subject: 'Hi', senderName: 'Rodger');
      final padded = padLetter(plain);
      expect(padded.length, 512);
      final o = openLetter(padded);
      expect(o.body, 'Ahoy');
      expect(o.subject, 'Hi');
      expect(o.fromName, 'Rodger');
      expect((jsonDecode(utf8.decode(padded)) as Map)['pad'], isA<String>());
    });

    test('each band, and the largest letter that fits stays within the envelope', () {
      expect(padLetter(composeLetter('x' * 600)).length, 2048);
      expect(padLetter(composeLetter('x' * 5000)).length, 8192);
      final big = padLetter(composeLetter('x' * 20000));
      expect(big.length, padBuckets.last);
      expect(fitsEnvelope(big), isTrue);
    });

    test('non-ASCII text is counted in bytes, not characters', () {
      final plain = composeLetter('é' * 300); // 600 bytes of body
      expect(padLetter(plain).length, 2048);
      expect(openLetter(padLetter(plain)).body, 'é' * 300);
    });

    test('something that is not an envelope is left alone', () {
      final raw = Uint8List.fromList(utf8.encode('plain text'));
      expect(padLetter(raw), raw);
    });

    test('a padded letter seals and opens', () async {
      final key = newPacketKey();
      final aad = letterAad('brry1a', 'brry1b');
      final ct = await encryptPacket(key, padLetter(composeLetter('sealed')), aad: aad);
      expect(ct.length, 512 + 12 + 16);
      expect(openLetter(await decryptPacket(key, ct, aad: aad)).body, 'sealed');
    });
  });

  group('low-order X25519 keys are refused (finding 11)', () {
    test('sealing to an all-zero public key fails', () async {
      expect(() => wrapToRecipient('00' * 32, [1, 2, 3]), throwsA(isA<FormatException>()));
    });

    test('a letter whose ephemeral key is all zero does not open', () async {
      final (priv, _) = await newEncryptionKeypair();
      final blob = {'epk': '00' * 32, 'nonce': '00' * 12, 'ct': '00' * 32};
      expect(() => unwrapFromSender(priv, blob), throwsA(isA<FormatException>()));
    });

    test('ordinary keys still seal and open', () async {
      final (priv, pub) = await newEncryptionKeypair();
      final blob = await wrapToRecipient(pub, utf8.encode('fine'));
      expect(utf8.decode(await unwrapFromSender(priv, blob)), 'fine');
    });
  });

  group('parcel rooms (finding 6)', () {
    const seeds = ['https://seed1.berrychain.link', 'https://seed2.berrychain.link'];
    test('the seeds are known rooms', () {
      expect(roomIsKnown('https://seed1.berrychain.link', seeds), isTrue);
      expect(roomIsKnown('https://seed2.berrychain.link/', seeds), isTrue);
    });
    test('another https host is not known, but may be fetched after asking', () {
      expect(roomIsKnown('https://tracker.example', seeds), isFalse);
      expect(roomIsSafeScheme('https://tracker.example'), isTrue);
      expect(roomHost('https://tracker.example/x'), 'tracker.example');
    });
    test('plain http is refused, except a devnet on this machine', () {
      expect(roomIsSafeScheme('http://seed1.berrychain.link'), isFalse);
      expect(roomIsKnown('http://seed1.berrychain.link', seeds), isFalse);
      expect(roomIsSafeScheme('http://127.0.0.1:8897'), isTrue);
      expect(roomIsSafeScheme('not a url'), isFalse);
    });
    test('fetching from a plain http room fails before any request', () async {
      final ref = ParcelRef(hash: '00', key: '00' * 32, size: 1, name: 'x', room: 'http://evil.example');
      expect(() => fetchParcel(ref), throwsA(anything));
    });
  });
}
