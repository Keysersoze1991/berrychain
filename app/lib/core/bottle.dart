import 'dart:typed_data';

import 'canonical.dart';
import 'crypto.dart';
import 'crypto.dart' as c;
import 'letters.dart';

/// A bottle (message in a bottle): a sealed note that travels phone to phone over the nearby link and
/// never touches the chain. Same envelope and same receiving keys as a letter,
/// so the recipient opens it exactly as a letter; but there is no block, no
/// fee, no coins and no record anywhere once the phones that carried it let it
/// go. Carriers see only ciphertext. The sender signs the note so carriers and
/// the recipient can throw away forgeries.
class Bottle {
  static const kindNote = 'bottle';
  static const kindAck = 'bottle_ack';
  static const ttlSeconds = 7 * 24 * 3600;
  static const maxBytes = 48 * 1024;

  /// The fields a signature covers (everything but the signature itself).
  static Map<String, dynamic> signable(Map<String, dynamic> n) {
    final m = Map<String, dynamic>.from(n)..remove('sig')..remove('id');
    return m;
  }

  static String idOf(Map<String, dynamic> n) => toHex(sha256(canonicalBytes(signable(n))));

  /// Seal [body] to [toEncPub] for [to], signed by the sender's key. Returns the
  /// note and the one-off packet key (kept by the sender so it can reread).
  static Future<(Map<String, dynamic>, Uint8List)> seal({
    required String from, required String signPriv, required String signPub, required String senderName,
    required String to, required String toEncPub, required String subject, required String body,
    String? replyTo, Uint8List? photoJpeg,
  }) async {
    final plain = composeLetter(body, subject: subject, replyTo: replyTo, senderName: senderName, photoJpeg: photoJpeg);
    if (!fitsEnvelope(plain)) throw ArgumentError('the note is too long for one envelope; shorten it or drop the picture');
    final key = newPacketKey();
    final aad = letterAad(from, to);
    final ct = await encryptPacket(key, plain, aad: aad);
    final note = <String, dynamic>{
      'v': 1, 'kind': kindNote, 'from': from, 'to': to, 'enc_pub': toEncPub, 'pubkey': signPub,
      'ciphertext': toHex(ct), 'ciphertext_hash': toHex(sha256(ct)), 'wrapped_key': await wrapToRecipient(toEncPub, key, aad: aad),
      'seal': 2, 'created': DateTime.now().millisecondsSinceEpoch ~/ 1000,
    };
    note['sig'] = await sign(signPriv, canonicalBytes(signable(note)));
    note['id'] = idOf(note);
    return (note, key);
  }

  /// A delivery receipt the recipient sends back, carried the same way.
  static Future<Map<String, dynamic>> ack({required String noteId, required String from, required String to, required String signPriv, required String signPub}) async {
    final a = <String, dynamic>{'v': 1, 'kind': kindAck, 'note': noteId, 'from': from, 'to': to, 'pubkey': signPub, 'created': DateTime.now().millisecondsSinceEpoch ~/ 1000};
    a['sig'] = await sign(signPriv, canonicalBytes(signable(a)));
    a['id'] = idOf(a);
    return a;
  }

  /// Well formed, signed by the address it claims, hash matches, and not stale.
  static Future<bool> verify(Map<String, dynamic> n) async {
    try {
      final kind = n['kind'];
      if (n['v'] != 1 || (kind != kindNote && kind != kindAck)) return false;
      for (final k in const ['from', 'to', 'pubkey', 'sig', 'id', 'created']) {
        if (n[k] == null) return false;
      }
      final from = n['from'] as String, to = n['to'] as String;
      if (!from.startsWith('brry1') || !to.startsWith('brry1') || from == to) return false;
      if (addressFromPubkey(n['pubkey'] as String) != from) return false;
      final age = DateTime.now().millisecondsSinceEpoch ~/ 1000 - (n['created'] as int);
      if (age > ttlSeconds || age < -3600) return false;
      if (idOf(n) != n['id']) return false;
      if (kind == kindNote) {
        final ct = fromHex(n['ciphertext'] as String);
        if (ct.isEmpty || ct.length > maxBytes || toHex(sha256(ct)) != n['ciphertext_hash']) return false;
        if (n['wrapped_key'] is! Map || n['enc_pub'] is! String) return false;
      } else if (n['note'] is! String) {
        return false;
      }
      return await verifyBytes(n['pubkey'] as String, canonicalBytes(signable(n)), n['sig'] as String);
    } catch (_) {
      return false;
    }
  }

  static Future<bool> verifyBytes(String pub, List<int> msg, String sig) => c.verify(pub, msg, sig);

  /// Open a note with the recipient's private key or the sender's kept packet key.
  static Future<OpenedLetter> open(Map<String, dynamic> n, {String? recipientEncPriv, List<int>? packetKey}) async {
    final aad = letterAad(n['from'] as String, n['to'] as String);
    final List<int> key;
    if (packetKey != null) {
      key = packetKey;
    } else if (recipientEncPriv != null) {
      key = await unwrapFromSender(recipientEncPriv, Map<String, dynamic>.from(n['wrapped_key'] as Map), aad: aad);
    } else {
      throw StateError('no key for this note on this phone');
    }
    return openLetter(await decryptPacket(key, fromHex(n['ciphertext'] as String), aad: aad));
  }
}
