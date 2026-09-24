import 'dart:convert';
import 'dart:io';

import 'crypto.dart';
import 'tx.dart' as t;

/// A wallet: one Ed25519 signing key (the address), one X25519 key (to
/// receive letters and packet keys), and the keys of letters this wallet
/// wrote so it can reread them. The file format is the reference wallet's,
/// so a wallet made on the phone opens on a PC and the other way round.
class Wallet {
  String label;
  final String signPriv, signPub, encPriv, encPub, address;
  final Map<String, String> packetKeys;
  String? path;
  String? passphrase; // remembered for the session so saves stay sealed

  Wallet._(this.label, this.signPriv, this.signPub, this.encPriv, this.encPub, this.address, this.packetKeys);

  static Future<Wallet> create({String label = ''}) async {
    final sp = toHex(randomBytes(32)), ep = toHex(randomBytes(32));
    final spub = await signPublicFromPrivate(sp);
    return Wallet._(label, sp, spub, ep, await encryptionPublicFromPrivate(ep), addressFromPubkey(spub), {});
  }

  /// Open a wallet file's JSON. Sealed files need [passphrase].
  static Future<Wallet> fromJson(Map<String, dynamic> d, {String? passphrase}) async {
    Map<String, dynamic> secrets;
    if (d.containsKey('encrypted')) {
      if (passphrase == null || passphrase.isEmpty) throw WalletLocked('this wallet is sealed; enter its passphrase');
      secrets = await unsealSecrets(d['encrypted'] as Map<String, dynamic>, passphrase);
    } else {
      secrets = d;
    }
    final sp = secrets['sign_priv'] as String;
    final spub = await signPublicFromPrivate(sp);
    final ep = secrets['enc_priv'] as String;
    final keys = <String, String>{
      for (final e in ((secrets['packet_keys'] as Map?) ?? {}).entries) e.key as String: e.value as String
    };
    final w = Wallet._((d['label'] as String?) ?? '', sp, spub, ep, await encryptionPublicFromPrivate(ep), addressFromPubkey(spub), keys);
    w.passphrase = passphrase;
    return w;
  }

  static Future<Wallet> load(String path, {String? passphrase}) async {
    final d = jsonDecode(await File(path).readAsString()) as Map<String, dynamic>;
    final w = await fromJson(d, passphrase: passphrase);
    w.path = path;
    return w;
  }

  /// Public fields of a wallet file, readable without the passphrase.
  static Map<String, dynamic> readPublic(String jsonText) {
    final d = jsonDecode(jsonText) as Map<String, dynamic>;
    return {'label': d['label'], 'address': d['address'], 'enc_pub': d['enc_pub'], 'encrypted': d.containsKey('encrypted')};
  }

  Map<String, dynamic> publicInfo() => {'label': label, 'address': address, 'sign_pub': signPub, 'enc_pub': encPub};

  Future<Map<String, dynamic>> toJson() async {
    final secrets = {'sign_priv': signPriv, 'enc_priv': encPriv, 'packet_keys': packetKeys};
    final p = passphrase;
    if (p == null || p.isEmpty) throw WalletLocked('refusing to write an unsealed wallet');
    return {...publicInfo(), 'encrypted': await sealSecrets(secrets, p)};
  }

  Future<void> save([String? to]) async {
    final target = to ?? path;
    if (target == null) throw StateError('wallet has no path');
    final tmp = File('$target.tmp');
    await tmp.writeAsString(jsonEncode(await toJson()), flush: true);
    await tmp.rename(target);
    path = target;
  }

  Future<Map<String, dynamic>> sign(Map<String, dynamic> tx) => t.signTx(tx, signPriv);
}
