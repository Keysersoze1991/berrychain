import 'dart:convert';
import 'store.dart';

import 'crypto.dart';
import 'mnemonic.dart';
import 'tx.dart' as t;

/// A wallet: one Ed25519 signing key (the address), its X25519 receiving
/// keys (the root one the words derive, plus any rotated ones), the keys of
/// letters this wallet wrote so it can reread them, and, for wallets made
/// from a recovery phrase, the phrase itself. The file format is the
/// reference wallet's, so a wallet made on the phone opens on a PC and the
/// other way round.
class Wallet {
  String label;
  final String signPriv, signPub, address;
  /// The current receiving key: what senders seal new letters to.
  String encPriv, encPub;
  /// The root receiving key: derived from the words (or the one the wallet
  /// was created with). Rotation backups are wrapped to it.
  final String encRootPriv, encRootPub;
  /// Every receiving key this wallet holds, public -> private.
  final Map<String, String> encKeys;
  final Map<String, String> packetKeys;
  final String? mnemonic;
  String? path;
  String? passphrase; // remembered for the session so saves stay sealed

  Wallet._(this.label, this.signPriv, this.signPub, this.encPriv, this.encPub, this.address, this.packetKeys, this.mnemonic,
      this.encRootPriv, this.encRootPub, this.encKeys);

  static Future<Wallet> _fromKeys(String label, String sp, String ep, Map<String, String> keys, String? mnemonic,
      {String? rootPriv, Map<String, String>? encKeys}) async {
    final spub = await signPublicFromPrivate(sp);
    final epub = await encryptionPublicFromPrivate(ep);
    final rp = rootPriv ?? ep;
    final rpub = rp == ep ? epub : await encryptionPublicFromPrivate(rp);
    final all = <String, String>{...?encKeys};
    all.putIfAbsent(rpub, () => rp);
    all.putIfAbsent(epub, () => ep);
    return Wallet._(label, sp, spub, ep, epub, addressFromPubkey(spub), keys, mnemonic, rp, rpub, all);
  }

  /// A brand-new wallet with a fresh twelve-word recovery phrase.
  static Future<Wallet> create({String label = ''}) => fromPhrase(newPhrase(), label: label);

  /// The wallet a recovery phrase describes, on any device.
  static Future<Wallet> fromPhrase(String phrase, {String label = ''}) async {
    final words = validatePhrase(phrase);
    final (sp, ep) = await keysFromPhrase(words);
    return _fromKeys(label, sp, ep, {}, words);
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
    Map<String, String> strMap(dynamic m) => <String, String>{for (final e in ((m as Map?) ?? {}).entries) e.key as String: e.value as String};
    final w = await _fromKeys((d['label'] as String?) ?? '', secrets['sign_priv'] as String, secrets['enc_priv'] as String, strMap(secrets['packet_keys']),
        secrets['mnemonic'] as String?, rootPriv: secrets['enc_root_priv'] as String?, encKeys: strMap(secrets['enc_keys']));
    w.passphrase = passphrase;
    return w;
  }

  static Future<Wallet> load(String path, {String? passphrase}) async {
    final text = await readText(path);
    if (text == null) throw StateError('no wallet at $path');
    final d = jsonDecode(text) as Map<String, dynamic>;
    final w = await fromJson(d, passphrase: passphrase);
    w.path = path;
    return w;
  }

  /// Public fields of a wallet file, readable without the passphrase.
  static Map<String, dynamic> readPublic(String jsonText) {
    final d = jsonDecode(jsonText) as Map<String, dynamic>;
    return {'label': d['label'], 'address': d['address'], 'enc_pub': d['enc_pub'], 'encrypted': d.containsKey('encrypted')};
  }

  /// The private half of one of this wallet's receiving keys, or null if the
  /// wallet does not hold it (rotated elsewhere without a backup, burned, or
  /// not yet recovered from the chain).
  String? keyFor(String encPubHex) => encKeys[encPubHex];

  /// Remember a receiving key; by default it becomes the current one.
  void addKey(String priv, String pub, {bool current = true}) {
    encKeys[pub] = priv;
    if (current) {
      encPriv = priv;
      encPub = pub;
    }
  }

  /// Forget a receiving key for good. The root key cannot be burned (the words
  /// would bring it straight back) and neither can the current one: rotate first.
  bool burnKey(String pub) {
    if (pub == encRootPub || pub == encPub) return false;
    return encKeys.remove(pub) != null;
  }

  Map<String, dynamic> publicInfo() => {'label': label, 'address': address, 'sign_pub': signPub, 'enc_pub': encPub};

  Future<Map<String, dynamic>> toJson() async {
    final secrets = <String, dynamic>{'sign_priv': signPriv, 'enc_priv': encPriv, 'packet_keys': packetKeys, 'enc_keys': encKeys, 'enc_root_priv': encRootPriv};
    if (mnemonic != null) secrets['mnemonic'] = mnemonic;
    final p = passphrase;
    if (p == null || p.isEmpty) throw WalletLocked('refusing to write an unsealed wallet');
    return {...publicInfo(), 'encrypted': await sealSecrets(secrets, p)};
  }

  Future<void> save([String? to]) async {
    final target = to ?? path;
    if (target == null) throw StateError('wallet has no path');
    await writeText(target, jsonEncode(await toJson()));
    path = target;
  }

  Future<Map<String, dynamic>> sign(Map<String, dynamic> tx) => t.signTx(tx, signPriv);
}
