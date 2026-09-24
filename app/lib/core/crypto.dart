import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as c;
import 'package:cryptography/cryptography.dart';
import 'package:pointycastle/export.dart' as pc;

import 'canonical.dart';

/// The chain's primitives, same choices as the reference node:
/// Ed25519 signatures, X25519 + HKDF-SHA256 + ChaCha20-Poly1305 key wrapping,
/// ChaCha20-Poly1305 content encryption, SHA-256 everywhere else, scrypt for
/// the wallet file.

const addressPrefix = 'brry1';
const _addressTag = 'berry-address';
const _ecies = 'berry-ecies-v1';
const _packetAad = 'berry-packet-v1';
const _keyCommit = 'berry-key-commit';
const _walletAad = 'berry-wallet-v1';

final _rng = Random.secure();

Uint8List randomBytes(int n) =>
    Uint8List.fromList(List<int>.generate(n, (_) => _rng.nextInt(256)));

String toHex(List<int> b) =>
    b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();

Uint8List fromHex(String h) {
  if (h.length.isOdd) throw const FormatException('odd hex length');
  final out = Uint8List(h.length ~/ 2);
  for (var i = 0; i < out.length; i++) {
    out[i] = int.parse(h.substring(2 * i, 2 * i + 2), radix: 16);
  }
  return out;
}

Uint8List sha256(List<int> data) => Uint8List.fromList(c.sha256.convert(data).bytes);
Uint8List sha256d(List<int> data) => sha256(sha256(data));
String hashObj(Object? obj) => toHex(sha256(canonicalBytes(obj)));

/// Big-endian integer view of a 32-byte digest, for target comparisons.
BigInt bigFromBytes(List<int> b) {
  var r = BigInt.zero;
  for (final x in b) {
    r = (r << 8) | BigInt.from(x);
  }
  return r;
}

// ---------------------------------------------------------------- signing

final _ed = Ed25519();
final _x = X25519();

Future<String> signPublicFromPrivate(String privHex) async {
  final kp = await _ed.newKeyPairFromSeed(fromHex(privHex));
  return toHex((await kp.extractPublicKey()).bytes);
}

Future<String> sign(String privHex, List<int> message) async {
  final kp = await _ed.newKeyPairFromSeed(fromHex(privHex));
  return toHex((await _ed.sign(message, keyPair: kp)).bytes);
}

Future<bool> verify(String pubHex, List<int> message, String sigHex) async {
  try {
    final pub = SimplePublicKey(fromHex(pubHex), type: KeyPairType.ed25519);
    return await _ed.verify(message, signature: Signature(fromHex(sigHex), publicKey: pub));
  } catch (_) {
    return false;
  }
}

String addressFromPubkey(String pubHex) {
  final payload = sha256(fromHex(pubHex)).sublist(0, 20);
  final checksum = sha256([...utf8.encode(_addressTag), ...payload]).sublist(0, 4);
  return addressPrefix + toHex(payload) + toHex(checksum);
}

bool isValidAddress(String? addr) {
  if (addr == null || !addr.startsWith(addressPrefix)) return false;
  final body = addr.substring(addressPrefix.length);
  if (body.length != 48) return false;
  final Uint8List raw;
  try {
    raw = fromHex(body);
  } on FormatException {
    return false;
  }
  final payload = raw.sublist(0, 20), checksum = raw.sublist(20);
  final want = sha256([...utf8.encode(_addressTag), ...payload]).sublist(0, 4);
  return toHex(want) == toHex(checksum);
}

// ------------------------------------------------------------- encryption

Future<String> encryptionPublicFromPrivate(String privHex) async {
  final kp = await _x.newKeyPairFromSeed(fromHex(privHex));
  return toHex((await kp.extractPublicKey()).bytes);
}

Future<Uint8List> _derive(List<int> shared, List<int> epk, List<int> rpk) async {
  final hkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);
  final k = await hkdf.deriveKey(
      secretKey: SecretKey(shared), nonce: [...epk, ...rpk], info: utf8.encode(_ecies));
  return Uint8List.fromList(await k.extractBytes());
}

final _aead = Chacha20.poly1305Aead();

Future<Uint8List> _aeadEncrypt(List<int> key, List<int> nonce, List<int> plaintext, List<int> aad) async {
  final box = await _aead.encrypt(plaintext, secretKey: SecretKey(key), nonce: nonce, aad: aad);
  return Uint8List.fromList([...box.cipherText, ...box.mac.bytes]);
}

Future<Uint8List> _aeadDecrypt(List<int> key, List<int> nonce, List<int> ctAndTag, List<int> aad) async {
  if (ctAndTag.length < 16) throw const FormatException('ciphertext too short');
  final ct = ctAndTag.sublist(0, ctAndTag.length - 16);
  final mac = Mac(ctAndTag.sublist(ctAndTag.length - 16));
  final pt = await _aead.decrypt(SecretBox(ct, nonce: nonce, mac: mac), secretKey: SecretKey(key), aad: aad);
  return Uint8List.fromList(pt);
}

/// ECIES: seal [plaintext] so only the holder of [recipientPubHex] can read it.
Future<Map<String, String>> wrapToRecipient(String recipientPubHex, List<int> plaintext) async {
  final rpk = fromHex(recipientPubHex);
  final ephSeed = randomBytes(32);
  final eph = await _x.newKeyPairFromSeed(ephSeed);
  final epk = (await eph.extractPublicKey()).bytes;
  final shared = await _x.sharedSecretKey(
      keyPair: eph, remotePublicKey: SimplePublicKey(rpk, type: KeyPairType.x25519));
  final key = await _derive(await shared.extractBytes(), epk, rpk);
  final nonce = randomBytes(12);
  final ct = await _aeadEncrypt(key, nonce, plaintext, epk);
  return {'epk': toHex(epk), 'nonce': toHex(nonce), 'ct': toHex(ct)};
}

Future<Uint8List> unwrapFromSender(String recipientPrivHex, Map<String, dynamic> blob) async {
  final kp = await _x.newKeyPairFromSeed(fromHex(recipientPrivHex));
  final rpk = (await kp.extractPublicKey()).bytes;
  final epk = fromHex(blob['epk'] as String);
  final shared = await _x.sharedSecretKey(
      keyPair: kp, remotePublicKey: SimplePublicKey(epk, type: KeyPairType.x25519));
  final key = await _derive(await shared.extractBytes(), epk, rpk);
  return _aeadDecrypt(key, fromHex(blob['nonce'] as String), fromHex(blob['ct'] as String), epk);
}

Uint8List newPacketKey() => randomBytes(32);

Future<Uint8List> encryptPacket(List<int> key, List<int> plaintext) async {
  final nonce = randomBytes(12);
  final ct = await _aeadEncrypt(key, nonce, plaintext, utf8.encode(_packetAad));
  return Uint8List.fromList([...nonce, ...ct]);
}

Future<Uint8List> decryptPacket(List<int> key, List<int> ciphertext) async {
  if (ciphertext.length < 12 + 16) throw const FormatException('ciphertext too short');
  return _aeadDecrypt(key, ciphertext.sublist(0, 12), ciphertext.sublist(12), utf8.encode(_packetAad));
}

String keyCommitment(List<int> key) => toHex(sha256([...utf8.encode(_keyCommit), ...key]));

// ------------------------------------------------------------ wallet seal

const scryptN = 1 << 15, scryptR = 8, scryptP = 1;

Uint8List _scrypt(String passphrase, List<int> salt, int n, int r, int p) {
  final s = pc.Scrypt()..init(pc.ScryptParameters(n, r, p, 32, Uint8List.fromList(salt)));
  final out = Uint8List(32);
  s.deriveKey(Uint8List.fromList(utf8.encode(passphrase)), 0, out, 0);
  return out;
}

class WalletLocked implements Exception {
  final String message;
  WalletLocked(this.message);
  @override
  String toString() => message;
}

/// Seal the wallet's secret fields under a passphrase, exactly the reference
/// wallet's `encrypted` blob: scrypt key, ChaCha20-Poly1305 over the
/// canonical JSON of the secrets, with a fixed associated-data tag.
Future<Map<String, dynamic>> sealSecrets(Map<String, dynamic> secrets, String passphrase) async {
  if (passphrase.isEmpty) throw ArgumentError('passphrase must not be empty');
  final salt = randomBytes(16), nonce = randomBytes(12);
  final key = _scrypt(passphrase, salt, scryptN, scryptR, scryptP);
  final ct = await _aeadEncrypt(key, nonce, canonicalBytes(secrets), utf8.encode(_walletAad));
  return {
    'kdf': 'scrypt', 'n': scryptN, 'r': scryptR, 'p': scryptP,
    'salt': toHex(salt), 'nonce': toHex(nonce), 'ct': toHex(ct),
  };
}

Future<Map<String, dynamic>> unsealSecrets(Map<String, dynamic> blob, String passphrase) async {
  if (blob['kdf'] != 'scrypt') throw WalletLocked('unsupported wallet kdf ${blob['kdf']}');
  final key = _scrypt(passphrase, fromHex(blob['salt'] as String), blob['n'] as int, blob['r'] as int, blob['p'] as int);
  try {
    final pt = await _aeadDecrypt(key, fromHex(blob['nonce'] as String), fromHex(blob['ct'] as String), utf8.encode(_walletAad));
    return jsonDecode(utf8.decode(pt)) as Map<String, dynamic>;
  } on SecretBoxAuthenticationError {
    throw WalletLocked('wrong passphrase');
  }
}
