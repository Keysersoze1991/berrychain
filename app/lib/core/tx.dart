import 'dart:typed_data';

import 'canonical.dart';
import 'crypto.dart';

/// Transaction construction, ids and signing, mirroring the reference node.
/// A transaction is a plain map so it serialises without ceremony.

class TxType {
  static const transfer = 'TRANSFER';
  static const registerLlm = 'REGISTER_LLM';
  static const gift = 'GIFT';
  static const sendLetter = 'SEND_LETTER';
  static const claimStarter = 'CLAIM_STARTER';
  static const claimGrant = 'CLAIM_GRANT';
}

const _sigFields = {'sig', 'pubkey', 'approvals'};

Map<String, dynamic> signableBody(Map<String, dynamic> tx) =>
    {for (final e in tx.entries) if (!_sigFields.contains(e.key)) e.key: e.value};

Uint8List signableBytes(Map<String, dynamic> tx) => canonicalBytes(signableBody(tx));

String txid(Map<String, dynamic> tx) => toHex(sha256(signableBytes(tx)));

Map<String, dynamic> buildTx(String type, String sender, int nonce, int fee, Map<String, dynamic> payload, String chainId) =>
    {'type': type, 'from': sender, 'nonce': nonce, 'fee': fee, 'chain_id': chainId, 'payload': payload};

Future<Map<String, dynamic>> signTx(Map<String, dynamic> tx, String signPrivHex) async {
  final pub = await signPublicFromPrivate(signPrivHex);
  if (addressFromPubkey(pub) != tx['from']) throw ArgumentError('private key does not match the sender address');
  tx['pubkey'] = pub;
  tx['sig'] = await sign(signPrivHex, signableBytes(tx));
  return tx;
}

/// Grind `payload.work_nonce` until the txid carries [bits] leading zero bits.
/// Works on the canonical bytes directly so each try is one SHA-256.
/// [onProgress] is called every 50,000 tries. Returns the nonce found.
int grindClaim(Map<String, dynamic> tx, int bits, {void Function(int tries)? onProgress}) {
  (tx['payload'] as Map<String, dynamic>)['work_nonce'] = 0;
  final template = canonicalJson(signableBody(tx));
  const marker = '"work_nonce":0';
  final at = template.indexOf(marker);
  if (at < 0 || template.indexOf(marker, at + 1) >= 0) throw StateError('cannot grind this claim');
  final head = template.substring(0, at + '"work_nonce":'.length).codeUnits;
  final tail = template.substring(at + marker.length).codeUnits;
  final limit = BigInt.one << (256 - bits);
  var n = 0;
  while (true) {
    final digest = sha256([...head, ...n.toString().codeUnits, ...tail]);
    if (bits == 0 || bigFromBytes(digest) < limit) break;
    n++;
    if (onProgress != null && n % 50000 == 0) onProgress(n);
  }
  (tx['payload'] as Map<String, dynamic>)['work_nonce'] = n;
  assert(bits == 0 || bigFromBytes(fromHex(txid(tx))) < limit);
  return n;
}
