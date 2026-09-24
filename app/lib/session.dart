import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

import 'core/crypto.dart';
import 'core/letters.dart';
import 'core/light.dart';
import 'core/node.dart';
import 'core/tx.dart';
import 'core/units.dart';
import 'core/wallet.dart';

/// Network constants for mainnet. The checkpoint and genesis are pinned so a
/// lying node cannot show this phone a different chain.
class Network {
  static const chainId = 'berry-1';
  static const genesisHash = '4ed5115c8e1bb4847c7d4bc8eeb6a2214c2906fc26849a4e5f5ac544b17c44fd';
  static const checkpointHeight = 94;
  static const checkpointHash = '000016e8e41005dc8b0bcc21f8d29a1c18a65712afac81e4c7871c6909324b8e';
  static const seeds = ['https://seed1.berrychain.link', 'https://seed2.berrychain.link'];
}

class LetterItem {
  final Map<String, dynamic> meta;
  bool verified;
  LetterItem(this.meta, {this.verified = false});
  String get id => meta['id'] as String;
  String get from => meta['from'] as String;
  String get to => meta['to'] as String;
  int get height => meta['height'] as int;
  int get amount => meta['amount'] as int;
  int get size => meta['size'] as int;
}

/// Everything the screens share: the unlocked wallet, the node connection,
/// the light client, and cached views of balance and letters.
class Session extends ChangeNotifier {
  Wallet? wallet;
  String? walletPath;
  bool hasWalletFile = false;
  List<String> nodeUrls = List.of(Network.seeds);
  late Node node;
  LightClient? light;

  int? balance;
  int? balanceOther; // the second seed's opinion, for the cross-check
  int? nodeHeight;
  int? starterAmount;
  int? letterFee;
  Map<String, dynamic>? registry; // this address's registry record, if any
  List<LetterItem> inbox = [];
  List<LetterItem> sent = [];
  String? lastError;
  bool busy = false;

  Session() {
    node = Node(nodeUrls.first);
  }

  Future<Directory> _dir() => getApplicationDocumentsDirectory();

  Future<void> init() async {
    final d = await _dir();
    walletPath = '${d.path}/wallet.json';
    hasWalletFile = await File(walletPath!).exists();
    final settings = File('${d.path}/settings.json');
    if (await settings.exists()) {
      try {
        final s = jsonDecode(await settings.readAsString()) as Map<String, dynamic>;
        final urls = (s['nodes'] as List?)?.cast<String>();
        if (urls != null && urls.isNotEmpty) nodeUrls = urls;
      } catch (_) {}
    }
    node = Node(nodeUrls.first);
    light = await LightClient.open(Profile.mainnet, Network.genesisHash,
        checkpointHeight: Network.checkpointHeight, checkpointHash: Network.checkpointHash, path: '${d.path}/headers-${Network.chainId}.json');
    notifyListeners();
  }

  Future<void> saveSettings(List<String> urls) async {
    nodeUrls = urls.where((u) => u.trim().isNotEmpty).map((u) => u.trim()).toList();
    if (nodeUrls.isEmpty) nodeUrls = List.of(Network.seeds);
    node = Node(nodeUrls.first);
    final d = await _dir();
    await File('${d.path}/settings.json').writeAsString(jsonEncode({'nodes': nodeUrls}));
    notifyListeners();
  }

  // -------------------------------------------------------------- wallet
  Future<void> createWallet(String label, String passphrase) async {
    final w = await Wallet.create(label: label);
    w.passphrase = passphrase;
    await w.save(walletPath);
    wallet = w;
    hasWalletFile = true;
    notifyListeners();
  }

  Future<void> importWallet(String jsonText, String passphrase) async {
    final d = jsonDecode(jsonText) as Map<String, dynamic>;
    final w = await Wallet.fromJson(d, passphrase: d.containsKey('encrypted') ? passphrase : null);
    w.passphrase = passphrase; // the copy on this phone is always sealed
    await w.save(walletPath);
    wallet = w;
    hasWalletFile = true;
    notifyListeners();
  }

  Future<void> unlock(String passphrase) async {
    wallet = await Wallet.load(walletPath!, passphrase: passphrase);
    notifyListeners();
  }

  Future<String> exportWalletJson() async => jsonEncode(await wallet!.toJson());

  void lock() {
    wallet = null;
    balance = null;
    inbox = [];
    sent = [];
    registry = null;
    notifyListeners();
  }

  // ------------------------------------------------------------- refresh
  Future<void> refresh() async {
    final w = wallet;
    if (w == null) return;
    busy = true;
    lastError = null;
    notifyListeners();
    try {
      final st = await node.status();
      nodeHeight = st['height'] as int?;
      starterAmount = st['starter_amount'] as int?;
      letterFee = st['letter_fee'] as int?;
      final a = await node.account(w.address);
      balance = a['balance'] as int;
      registry = a['llm'] as Map<String, dynamic>?;
      inbox = (await node.letters(to: w.address)).map((m) => LetterItem(m)).toList()..sort((x, y) => y.height.compareTo(x.height));
      sent = (await node.letters(from: w.address)).map((m) => LetterItem(m)).toList()..sort((x, y) => y.height.compareTo(x.height));
      // second opinion on the balance from another seed, if there is one
      balanceOther = null;
      if (nodeUrls.length > 1) {
        try {
          balanceOther = (await Node(nodeUrls[1]).account(w.address))['balance'] as int;
        } catch (_) {}
      }
      await _verifyChain();
    } on NodeError catch (e) {
      lastError = e.message;
    } on VerifyError catch (e) {
      lastError = 'chain check failed: ${e.message}';
    } catch (e) {
      lastError = '$e';
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  Future<void> _verifyChain() async {
    final lc = light;
    if (lc == null) return;
    for (final url in nodeUrls.skip(1)) {
      try {
        await lc.sync(Node(url));
      } catch (_) {}
    }
    await lc.sync(node);
    // letters with coins attached are worth proving; content needs no proof
    for (final l in inbox.where((l) => l.amount > 0 && !l.verified)) {
      try {
        await lc.verifyTx(node, l.id);
        l.verified = true;
      } catch (_) {}
    }
  }

  int get verifiedHeight => light?.height ?? -1;

  // ---------------------------------------------------------------- acts
  Future<int> claimStarter(String name) async {
    final w = wallet!;
    final info = await node.params();
    final bits = (info['starter_claim_work_bits'] as int?) ?? 0;
    final payload = {'name': name, 'kind': 'person', 'model_family': '', 'operator': '', 'description': '', 'enc_pub': w.encPub, 'work_nonce': 0};
    final tx = buildTx(TxType.claimStarter, w.address, await node.nextNonce(w.address), minFee, payload, Network.chainId);
    final nonce = await compute(_grindInIsolate, {'tx': tx, 'bits': bits});
    (tx['payload'] as Map<String, dynamic>)['work_nonce'] = nonce;
    await w.sign(tx);
    await node.sendTx(tx);
    return (info['starter_amount'] as int?) ?? 0;
  }

  Future<String> send(String to, int amountSeeds, String memo) async {
    final w = wallet!;
    if (!isValidAddress(to)) throw ArgumentError('that is not a BerryChain address');
    final tx = buildTx(TxType.transfer, w.address, await node.nextNonce(w.address), minFee, {'to': to, 'amount': amountSeeds, 'memo': memo}, Network.chainId);
    await w.sign(tx);
    return node.sendTx(tx);
  }

  Future<String> sendLetter(String to, String subject, String body, int amountSeeds, {String? replyTo}) async {
    final w = wallet!;
    if (!isValidAddress(to)) throw ArgumentError('that is not a BerryChain address');
    final acct = await node.account(to);
    final reg = acct['llm'] as Map<String, dynamic>?;
    final encPub = reg?['enc_pub'] as String?;
    if (encPub == null) throw ArgumentError('that address has not claimed a starter or registered, so it has no receiving key yet');
    final key = newPacketKey();
    final ct = await encryptPacket(key, composeLetter(body, subject: subject, replyTo: replyTo, senderName: w.label));
    if (ct.length > 32 * 1024) throw ArgumentError('letter too long: the limit is 32 KB');
    final fee = letterFee ?? ((await node.status())['letter_fee'] as int? ?? minFee);
    final payload = {
      'to': to, 'enc_pub': encPub, 'ciphertext': toHex(ct), 'ciphertext_hash': toHex(sha256(ct)),
      'wrapped_key': await wrapToRecipient(encPub, key), 'amount': amountSeeds,
    };
    final tx = buildTx(TxType.sendLetter, w.address, await node.nextNonce(w.address), fee, payload, Network.chainId);
    await w.sign(tx);
    final id = txid(tx);
    w.packetKeys[id] = toHex(key);
    await w.save();
    await node.sendTx(tx);
    return id;
  }

  Future<OpenedLetter> readLetter(LetterItem l) async {
    final w = wallet!;
    final full = await node.letter(l.id);
    final List<int> key;
    if (full['to'] == w.address) {
      key = await unwrapFromSender(w.encPriv, Map<String, dynamic>.from(full['wrapped_key'] as Map));
    } else if (w.packetKeys.containsKey(l.id)) {
      key = fromHex(w.packetKeys[l.id]!);
    } else {
      throw StateError('this letter is not addressed to you');
    }
    final ct = fromHex((full['ciphertext'] as String?) ?? '');
    if (ct.isEmpty || toHex(sha256(ct)) != full['ciphertext_hash']) throw StateError('the node served a letter that does not match the chain');
    return openLetter(await decryptPacket(key, ct));
  }
}

int _grindInIsolate(Map<String, dynamic> args) =>
    grindClaim(Map<String, dynamic>.from(args['tx'] as Map), args['bits'] as int);
