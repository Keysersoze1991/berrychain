import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:berrychain_app/core/canonical.dart';
import 'package:berrychain_app/core/crypto.dart';
import 'package:berrychain_app/core/letters.dart';
import 'package:berrychain_app/core/light.dart';
import 'package:berrychain_app/core/mnemonic.dart';
import 'package:berrychain_app/core/tx.dart';
import 'package:berrychain_app/core/units.dart';
import 'package:berrychain_app/core/wallet.dart';
import 'package:flutter_test/flutter_test.dart';

/// Every value here was produced by the reference Python implementation
/// (app/tool/make_vectors.py). If the phone disagrees with any of them it
/// would sign, seal or verify something the chain rejects.
void main() {
  final v = jsonDecode(File('test/vectors.json').readAsStringSync()) as Map<String, dynamic>;

  test('canonical json matches python byte for byte', () {
    final c = v['canonical'] as Map<String, dynamic>;
    expect(toHex(canonicalBytes(c['obj'])), c['bytes_hex']);
    expect(hashObj(c['obj']), c['sha256']);
  });

  test('keys and address', () async {
    expect(await signPublicFromPrivate(v['sign_priv']), v['sign_pub']);
    expect(await encryptionPublicFromPrivate(v['enc_priv']), v['enc_pub']);
    expect(await encryptionPublicFromPrivate(v['enc_priv_2']), v['enc_pub_2']);
    expect(addressFromPubkey(v['sign_pub']), v['address']);
    expect(isValidAddress(v['address']), isTrue);
    expect(isValidAddress('${(v['address'] as String).substring(0, 52)}0'), isFalse);
    expect(isValidAddress('brry1nope'), isFalse);
  });

  test('transfer: txid, signable bytes, signature verifies, resigning reproduces', () async {
    final tr = v['transfer'] as Map<String, dynamic>;
    final tx = Map<String, dynamic>.from(tr['tx'] as Map);
    expect(txid(tx), tr['txid']);
    expect(toHex(signableBytes(tx)), tr['signable_hex']);
    expect(await verify(tx['pubkey'], signableBytes(tx), tx['sig']), isTrue);
    final again = buildTx(tx['type'], tx['from'], tx['nonce'], tx['fee'], Map<String, dynamic>.from(tx['payload']), tx['chain_id']);
    await signTx(again, v['sign_priv']);
    expect(again['sig'], tx['sig']); // Ed25519 is deterministic
    expect(again['pubkey'], tx['pubkey']);
  });

  test('claim: work bits and grinding agree', () async {
    final cl = v['claim'] as Map<String, dynamic>;
    final tx = Map<String, dynamic>.from(cl['tx'] as Map);
    expect(txid(tx), cl['txid']);
    final bits = cl['work_bits'] as int;
    expect(bigFromBytes(fromHex(txid(tx))) < (BigInt.one << (256 - bits)), isTrue);
    final mine = buildTx(tx['type'], tx['from'], tx['nonce'], tx['fee'], Map<String, dynamic>.from(tx['payload']), tx['chain_id']);
    final n = grindClaim(mine, bits);
    expect(n, (tx['payload'] as Map)['work_nonce']); // same search from 0 finds the same nonce
    expect(txid(mine), cl['txid']);
  });

  test('packet encryption and key wrapping', () async {
    final p = v['packet'] as Map<String, dynamic>;
    final key = fromHex(p['key_hex']);
    expect(utf8.decode(await decryptPacket(key, fromHex(p['ciphertext_hex']))), p['plaintext']);
    expect(keyCommitment(key), p['key_commitment']);
    expect(toHex(sha256(fromHex(p['ciphertext_hex']))), p['ciphertext_sha256']);
    expect(toHex(await unwrapFromSender(v['enc_priv_2'], Map<String, dynamic>.from(p['wrapped_to_2']))), p['key_hex']);
    await expectLater(unwrapFromSender(v['enc_priv'], Map<String, dynamic>.from(p['wrapped_to_2'])), throwsA(anything));
    // our own round trip, both directions
    final blob = await wrapToRecipient(v['enc_pub'], key);
    expect(toHex(await unwrapFromSender(v['enc_priv'], blob)), p['key_hex']);
    final ct = await encryptPacket(key, utf8.encode('round trip'));
    expect(utf8.decode(await decryptPacket(key, ct)), 'round trip');
  });

  test('wallet file from the python cli opens, and ours opens there too (same format)', () async {
    final wv = v['wallet'] as Map<String, dynamic>;
    final w = await Wallet.fromJson(Map<String, dynamic>.from(wv['file']), passphrase: wv['passphrase']);
    expect(w.address, v['address']);
    expect(w.signPriv, v['sign_priv']);
    expect(w.encPriv, v['enc_priv']);
    expect(w.packetKeys, (wv['secrets'] as Map)['packet_keys']);
    await expectLater(Wallet.fromJson(Map<String, dynamic>.from(wv['file']), passphrase: 'wrong'), throwsA(isA<WalletLocked>()));
    final sealed = await w.toJson();
    expect(sealed['address'], v['address']);
    final back = await Wallet.fromJson(sealed, passphrase: wv['passphrase']);
    expect(back.signPriv, v['sign_priv']);
  }, timeout: const Timeout(Duration(minutes: 2)));

  test('mainnet genesis and first blocks hash and verify', () async {
    final m = v['mainnet'] as Map<String, dynamic>;
    final b0 = Map<String, dynamic>.from(m['block0']), b1 = Map<String, dynamic>.from(m['block1']);
    for (final b in [b0, b1]) {
      final ids = (b['txs'] as List).map((t) => txid(Map<String, dynamic>.from(t as Map))).toList();
      expect(merkleRoot(ids), b['merkle_root']);
      expect(blockHash(b), b['hash']);
      if (b['height'] != 0) expect(powOk(b), isTrue); // genesis is not mined
    }
    expect(b0['hash'], m['genesis_hash']);
    final hdrs = (m['headers'] as List).cast<Map<String, dynamic>>();
    final lc = LightClient(Profile.mainnet, m['genesis_hash']);
    final now = (hdrs.last['timestamp'] as int) + 60;
    lc.checkHeader(hdrs[1], hdrs, 1, 0, now);
    lc.checkHeader(hdrs[2], hdrs, 2, 0, now);
    final tampered = Map<String, dynamic>.from(hdrs[2])..['nonce'] = (hdrs[2]['nonce'] as int) + 1;
    expect(() => lc.checkHeader(tampered, hdrs, 2, 0, now), throwsA(isA<VerifyError>()));
    final w = workForTarget(hexToTarget(hdrs[1]['target'])) + workForTarget(hexToTarget(hdrs[2]['target']));
    expect(w.toString(), (m['work_0_2']).toString());
    expect(targetToHex(Profile.mainnet.maxTarget), m['max_target_hex']);
    final mk = v['merkle'] as Map<String, dynamic>;
    expect(merkleRoot(['11' * 32, '22' * 32, '33' * 32]), mk['three']);
    expect(merkleRoot([]), mk['empty']);
  });

  test('recovery phrases match the reference and the BIP-39 vector', () async {
    final m = v['mnemonic'] as Map<String, dynamic>;
    expect(newPhrase(Uint8List(16)), m['zero_phrase']);
    expect(toHex(await seedFromPhrase(m['zero_phrase'])), m['zero_seed_hex']);
    final (sp, ep) = await keysFromPhrase(m['zero_phrase']);
    expect([sp, ep], [m['zero_sign_priv'], m['zero_enc_priv']]);
    expect(newPhrase(fromHex(m['entropy_hex'])), m['phrase']);
    final w = await Wallet.fromPhrase(m['phrase']);
    expect(w.address, m['address']);
    expect(w.encPriv, m['enc_priv']);
    expect(w.mnemonic, m['phrase']);
    expect(() => validatePhrase('abandon abandon abandon'), throwsFormatException);
    expect(() => validatePhrase((m['phrase'] as String).replaceFirst(RegExp(r'^\w+'), 'zoo')), throwsFormatException);
    final fresh = await Wallet.create(label: 'x');
    final again = await Wallet.fromPhrase(fresh.mnemonic!);
    expect(again.address, fresh.address);
    fresh.passphrase = 'correct horse';
    final back = await Wallet.fromJson(await fresh.toJson(), passphrase: 'correct horse');
    expect(back.mnemonic, fresh.mnemonic);
  }, timeout: const Timeout(Duration(minutes: 2)));

  test('letter envelope and units', () {
    final env = openLetter(composeLetter('Bring the charts.', subject: 'Tomorrow', replyTo: 'abc', senderName: 'alice'));
    expect([env.subject, env.body, env.replyTo, env.fromName], ['Tomorrow', 'Bring the charts.', 'abc', 'alice']);
    expect(openLetter(utf8.encode('plain')).body, 'plain');
    final jpeg = Uint8List.fromList([0xff, 0xd8, 1, 2, 3]);
    final withPhoto = openLetter(composeLetter('look', photoJpeg: jpeg));
    expect(withPhoto.photoJpeg, jpeg);
    expect(withPhoto.body, 'look');
    expect(textBudget(photoJpeg: jpeg) < textBudget(), isTrue);
    expect(fitsEnvelope(composeLetter('x' * 40000)), isFalse);
    expect(openLetter([0xff, 0x00]).isHex, isTrue);
    expect(formatBerry(500000000), '5');
    expect(formatBerry(499990000), '4.9999');
    expect(formatBerry(123456789012), '1,234.56789012');
    expect(parseBerry('0.25'), 25000000);
    expect(parseBerry('1,000'), 100000000000);
    expect(() => parseBerry('1.123456789'), throwsFormatException);
  });
}
