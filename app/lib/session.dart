import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:workmanager/workmanager.dart';

import 'background.dart';
import 'core/store.dart';

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
  static const harbourmaster = 'brry1eba16ee17764413d1c1aa73a5ba43521880b9e5f4dd010e2';
  /// The Harbourmaster's purse, as published on berrychain.link. The prize and bonus halve
  /// every 5,000 registered accounts (never below 0.5 BERRY); the welcome is flat.
  static const welcomeTipBerry = '0.2';
  static const prizeBerry = '5';
  static const site = 'https://berrychain.link';

  /// The note the share sheet sends to a friend.
  static String invite(String address, String name) {
    final who = name.isEmpty ? 'me' : '$name (that is me)';
    return 'Hi! I am using BerryChain to send sealed letters: private mail only the person I write to can open. '
        'Get the app at $site and write to $who at this address:\n\n$address\n\n'
        'Your first letter to the Harbourmaster earns a small welcome, and the best letter each week wins a prize.';
  }
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

/// Someone this wallet has written to or heard from, or a well-known address.
class Contact {
  final String address;
  String name;      // the name they registered on the chain, if any
  String nickname;  // what you call them, kept on this phone only
  int letters;      // letters exchanged
  int lastHeight;
  Contact(this.address, {this.name = '', this.nickname = '', this.letters = 0, this.lastHeight = 0});
  String get label {
    if (nickname.isNotEmpty) return nickname;
    if (address == Network.harbourmaster) return 'the Harbourmaster'; // his chain name is the genesis label
    return name.isNotEmpty ? name : address.substring(0, 12);
  }
}

/// A letter being written, kept on this phone until it is sent or discarded.
class Draft {
  final String id;
  String to, subject, body;
  String? replyTo, groupId, photoB64;
  int updated;
  Draft(this.id, {this.to = '', this.subject = '', this.body = '', this.replyTo, this.groupId, this.photoB64, this.updated = 0});
  Map<String, dynamic> toJson() => {'id': id, 'to': to, 'subject': subject, 'body': body, 'reply_to': replyTo, 'group_id': groupId, 'photo_b64': photoB64, 'updated': updated};
  static Draft fromJson(Map<String, dynamic> j) => Draft(j['id'] as String,
      to: (j['to'] as String?) ?? '', subject: (j['subject'] as String?) ?? '', body: (j['body'] as String?) ?? '',
      replyTo: j['reply_to'] as String?, groupId: j['group_id'] as String?, photoB64: j['photo_b64'] as String?, updated: (j['updated'] as int?) ?? 0);
  bool get isEmpty => to.isEmpty && subject.isEmpty && body.trim().isEmpty && photoB64 == null;
}

/// A grant the account can earn by corresponding, and where it stands.
class EarnedGrant {
  final String tier, title;
  final int need, amount;
  final bool taken;
  EarnedGrant(this.tier, this.title, this.need, this.amount, this.taken);
}

/// Everything the screens share: the unlocked wallet, the node connection,
/// the light client, and cached views of balance and letters.
class Session extends ChangeNotifier {
  Wallet? wallet;
  String? walletPath;
  bool hasWalletFile = false;
  List<String> nodeUrls = List.of(Network.seeds);
  bool backgroundChecks = true;
  late Node node;
  LightClient? light;

  int? balance;
  int? balanceOther; // the second seed's opinion, for the cross-check
  int? nodeHeight;
  int? starterAmount;
  int? letterFee;
  int correspondents = 0;
  Map<String, dynamic>? registry; // this address's registry record, if any
  Map<String, dynamic>? chainParams;
  List<LetterItem> _inboxAll = [];
  List<LetterItem> _sentAll = [];
  List<Contact> contacts = [];
  List<LetterGroup> groups = [];
  List<Draft> drafts = [];
  final Set<String> _hidden = {};
  bool showRemoved = false;
  final Map<String, String> _nicknames = {};
  final Map<String, String> _nameCache = {};

  /// Letters, without the ones removed on this phone (unless [showRemoved]).
  List<LetterItem> get inbox => showRemoved ? _inboxAll : _inboxAll.where((l) => !_hidden.contains(l.id)).toList();
  List<LetterItem> get sent => showRemoved ? _sentAll : _sentAll.where((l) => !_hidden.contains(l.id)).toList();
  bool isRemoved(String id) => _hidden.contains(id);
  int get removedCount => _hidden.length;
  String? lastError;
  bool busy = false;

  Session() {
    node = Node(nodeUrls.first);
  }

  Future<void> init() async {
    final d = await storeDir();
    walletPath = '${d}wallet.json';
    hasWalletFile = await existsText(walletPath!);
    final settings = await readText('${d}settings.json');
    if (settings != null) {
      try {
        final s = jsonDecode(settings) as Map<String, dynamic>;
        final urls = (s['nodes'] as List?)?.cast<String>();
        if (urls != null && urls.isNotEmpty) nodeUrls = urls;
        backgroundChecks = (s['background'] as bool?) ?? true;
      } catch (_) {}
    }
    node = Node(nodeUrls.first);
    if (!kIsWeb) {
      try {
        await Workmanager().initialize(callbackDispatcher);
        await initNotifications();
      } catch (_) {}
    }
    final nick = await readText('${d}contacts.json');
    if (nick != null) {
      try {
        final m = jsonDecode(nick) as Map<String, dynamic>;
        m.forEach((k, v) => _nicknames[k] = v as String);
      } catch (_) {}
    }
    await _loadLocal(d);
    light = await LightClient.open(Profile.mainnet, Network.genesisHash,
        checkpointHeight: Network.checkpointHeight, checkpointHash: Network.checkpointHash, path: '${d}headers-${Network.chainId}.json');
    notifyListeners();
  }

  Future<void> saveSettings(List<String> urls, {bool? background}) async {
    nodeUrls = urls.where((u) => u.trim().isNotEmpty).map((u) => u.trim()).toList();
    if (nodeUrls.isEmpty) nodeUrls = List.of(Network.seeds);
    node = Node(nodeUrls.first);
    if (background != null) backgroundChecks = background;
    await writeText('${await storeDir()}settings.json', jsonEncode({'nodes': nodeUrls, 'background': backgroundChecks}));
    try {
      if (backgroundChecks && wallet != null) {
        await enableBackgroundChecks();
      } else {
        await disableBackgroundChecks();
      }
    } catch (_) {}
    notifyListeners();
  }

  // -------------------------------------------------------------- wallet
  /// Makes a wallet from a fresh recovery phrase and returns the phrase.
  Future<String> createWallet(String label, String passphrase) async {
    final w = await Wallet.create(label: label);
    w.passphrase = passphrase;
    await w.save(walletPath);
    wallet = w;
    hasWalletFile = true;
    notifyListeners();
    return w.mnemonic!;
  }

  Future<void> recoverWallet(String phrase, String label, String passphrase) async {
    final w = await Wallet.fromPhrase(phrase, label: label);
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
    _inboxAll = [];
    _sentAll = [];
    registry = null;
    correspondents = 0;
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
      chainParams = await node.params();
      final a = await node.account(w.address);
      balance = a['balance'] as int;
      registry = a['llm'] as Map<String, dynamic>?;
      correspondents = (a['correspondents'] as int?) ?? 0;
      _inboxAll = (await node.letters(to: w.address)).map((m) => LetterItem(m)).toList()..sort((x, y) => y.height.compareTo(x.height));
      _sentAll = (await node.letters(from: w.address)).map((m) => LetterItem(m)).toList()..sort((x, y) => y.height.compareTo(x.height));
      balanceOther = null;
      if (nodeUrls.length > 1) {
        try {
          balanceOther = (await Node(nodeUrls[1]).account(w.address))['balance'] as int;
        } catch (_) {}
      }
      await _buildContacts();
      await _verifyChain();
      if (nodeHeight != null) {
        try {
          await markSeen(address: w.address, height: nodeHeight!, nodes: nodeUrls);
          if (backgroundChecks) await enableBackgroundChecks();
        } catch (_) {}
      }
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
    for (final l in _inboxAll.where((l) => l.amount > 0 && !l.verified)) {
      try {
        await lc.verifyTx(node, l.id);
        l.verified = true;
      } catch (_) {}
    }
  }

  int get verifiedHeight => light?.height ?? -1;

  /// Everyone this wallet has corresponded with, newest first, plus the
  /// Harbourmaster so there is always someone to write to. Names come from
  /// the chain registry and are cached; nicknames are yours alone.
  Future<void> _buildContacts() async {
    final me = wallet!.address;
    final seen = <String, Contact>{};
    void note(String addr, int height) {
      if (addr == me) return;
      final c = seen.putIfAbsent(addr, () => Contact(addr));
      c.letters++;
      if (height > c.lastHeight) c.lastHeight = height;
    }
    for (final l in _inboxAll) {
      note(l.from, l.height);
    }
    for (final l in _sentAll) {
      note(l.to, l.height);
    }
    seen.putIfAbsent(Network.harbourmaster, () => Contact(Network.harbourmaster));
    for (final c in seen.values) {
      c.nickname = _nicknames[c.address] ?? '';
      if (c.address == Network.harbourmaster) {
        c.name = 'the Harbourmaster'; // his chain name is the genesis label; people know him by this one
        continue;
      }
      if (c.name.isEmpty) {
        var n = _nameCache[c.address];
        if (n == null) {
          try {
            n = (((await node.account(c.address))['llm'] as Map?)?['name'] as String?) ?? '';
          } catch (_) {
            n = '';
          }
          if (n.isNotEmpty) _nameCache[c.address] = n;
        }
        c.name = n;
      }
    }
    contacts = seen.values.toList()
      ..sort((a, b) {
        if (a.address == Network.harbourmaster && a.letters == 0) return 1;
        if (b.address == Network.harbourmaster && b.letters == 0) return -1;
        return b.lastHeight.compareTo(a.lastHeight);
      });
  }

  Future<void> setNickname(String address, String nickname) async {
    if (nickname.trim().isEmpty) {
      _nicknames.remove(address);
    } else {
      _nicknames[address] = nickname.trim();
    }
    for (final c in contacts) {
      if (c.address == address) c.nickname = _nicknames[address] ?? '';
    }
    await writeText('${await storeDir()}contacts.json', jsonEncode(_nicknames));
    notifyListeners();
  }

  // ------------------------------------------------ kept on this phone only
  Future<void> _loadLocal(String d) async {
    try {
      final g = await readText('${d}groups.json');
      if (g != null) groups = (jsonDecode(g) as List).map(LetterGroup.fromJson).whereType<LetterGroup>().toList();
    } catch (_) {}
    try {
      final t = await readText('${d}drafts.json');
      if (t != null) drafts = (jsonDecode(t) as List).map((j) => Draft.fromJson(Map<String, dynamic>.from(j as Map))).toList();
    } catch (_) {}
    try {
      final h = await readText('${d}hidden.json');
      if (h != null) {
        final m = jsonDecode(h) as Map<String, dynamic>;
        _hidden.addAll(((m['ids'] as List?) ?? []).cast<String>());
        showRemoved = (m['show'] as bool?) ?? false;
      }
    } catch (_) {}
  }

  Future<void> _saveGroups() async => writeText('${await storeDir()}groups.json', jsonEncode(groups.map((g) => g.toJson()).toList()));
  Future<void> _saveDrafts() async => writeText('${await storeDir()}drafts.json', jsonEncode(drafts.map((d) => d.toJson()).toList()));
  Future<void> _saveHidden() async => writeText('${await storeDir()}hidden.json', jsonEncode({'ids': _hidden.toList(), 'show': showRemoved}));

  /// The name to show for an address: your nickname, the name they registered
  /// on the chain, or nothing. Looks the chain up once per address.
  Future<String> lookupName(String address) async {
    if (address == Network.harbourmaster) return 'the Harbourmaster';
    final nick = _nicknames[address];
    if (nick != null && nick.isNotEmpty) return nick;
    final cached = _nameCache[address];
    if (cached != null) return cached;
    try {
      final n = (((await node.account(address))['llm'] as Map?)?['name'] as String?) ?? '';
      if (n.isNotEmpty) _nameCache[address] = n;
      return n;
    } catch (_) {
      return '';
    }
  }

  /// Whether an address has a receiving key, so a letter can be sealed to it.
  Future<bool> canReceiveLetters(String address) async {
    try {
      return (((await node.account(address))['llm'] as Map?)?['enc_pub'] as String?) != null;
    } catch (_) {
      return false;
    }
  }

  LetterGroup? groupById(String? id) {
    if (id == null) return null;
    for (final g in groups) {
      if (g.id == id) return g;
    }
    return null;
  }

  /// A group's id is derived from its name and members, so the same group made
  /// on two phones (or received in a letter) is recognised as one.
  static String groupIdFor(String name, List<String> members) {
    final sorted = [...members]..sort();
    return toHex(sha256(utf8.encode('${name.trim()}\n${sorted.join('\n')}'))).substring(0, 16);
  }

  Future<LetterGroup> saveGroup(String name, List<String> members, {String? id}) async {
    final me = wallet?.address;
    final clean = members.where((m) => m != me).toSet().toList();
    final g = LetterGroup(id ?? groupIdFor(name, clean), name.trim(), clean);
    groups.removeWhere((x) => x.id == g.id);
    groups.insert(0, g);
    await _saveGroups();
    notifyListeners();
    return g;
  }

  Future<void> deleteGroup(String id) async {
    groups.removeWhere((g) => g.id == id);
    await _saveGroups();
    notifyListeners();
  }

  /// When a group letter arrives, remember the group so you can reply to all.
  /// Returns true if it was new to this phone.
  Future<bool> adoptGroup(LetterGroup g, String sender) async {
    if (groupById(g.id) != null) return false;
    final members = {...g.members, sender}..remove(wallet?.address);
    await saveGroup(g.name, members.toList(), id: g.id);
    return true;
  }

  Future<void> saveDraft(Draft d) async {
    d.updated = DateTime.now().millisecondsSinceEpoch;
    drafts.removeWhere((x) => x.id == d.id);
    if (!d.isEmpty) drafts.insert(0, d);
    await _saveDrafts();
    notifyListeners();
  }

  Future<void> deleteDraft(String id) async {
    drafts.removeWhere((x) => x.id == id);
    await _saveDrafts();
    notifyListeners();
  }

  /// Remove a letter from this phone's lists. The sealed copy stays on the
  /// chain, as every letter does; only the key that opens it can ever read it.
  Future<void> removeLetter(String id) async {
    _hidden.add(id);
    await _saveHidden();
    notifyListeners();
  }

  Future<void> restoreLetter(String id) async {
    _hidden.remove(id);
    await _saveHidden();
    notifyListeners();
  }

  Future<void> setShowRemoved(bool v) async {
    showRemoved = v;
    await _saveHidden();
    notifyListeners();
  }

  /// The grants this account can earn by corresponding, with current amounts.
  List<EarnedGrant> get earnedGrants {
    final reg = registry;
    if (reg == null) return [];
    final tiers = (chainParams?['grant_tiers'] as Map?) ?? {};
    final amounts = (chainParams?['current_amounts'] as Map?) ?? {};
    final taken = ((reg['grants'] as List?) ?? []).map((g) => (g as Map)['tier'] as String).toSet();
    int need(String t, int fallback) => ((tiers[t] as Map?)?['min_correspondents'] as int?) ?? fallback;
    int amount(String t, int fallback) => (amounts[t] as int?) ?? fallback;
    final seatsLeft = ((chainParams?['founding_slots'] as int?) ?? 1000) - ((chainParams?['founding_seats_taken'] as int?) ?? 0);
    return [
      EarnedGrant('founding', 'Founding seat', (chainParams?['founding_min_correspondents'] as int?) ?? 3,
          (chainParams?['founding_grant'] as int?) ?? 150 * seedsPerBerry, (reg['founding'] as bool? ?? false) || seatsLeft <= 0),
      EarnedGrant('service-1', 'Service grant', need('service-1', 10), amount('service-1', 5 * seedsPerBerry), taken.contains('service-1')),
      EarnedGrant('service-2', 'Second service grant', need('service-2', 100), amount('service-2', 50 * seedsPerBerry), taken.contains('service-2')),
    ];
  }

  // ---------------------------------------------------------------- acts
  /// Live text for the busy sheet while a claim grinds ("1,200,000 tries so far").
  final ValueNotifier<String> claimProgress = ValueNotifier('');

  Future<Map<String, dynamic>> _claim(String type, Map<String, dynamic> payload) async {
    final w = wallet!;
    final info = chainParams ?? await node.params();
    final bits = (info['starter_claim_work_bits'] as int?) ?? 0;
    final tx = buildTx(type, w.address, await node.nextNonce(w.address), minFee, {...payload, 'work_nonce': 0}, Network.chainId);
    claimProgress.value = '';
    final int nonce;
    if (kIsWeb) {
      // One thread in a browser: grind in slices so the page stays alive and the count moves.
      var last = 0;
      nonce = await grindClaimAsync(tx, bits, onProgress: (n) {
        if (n - last >= 50000) {
          last = n;
          claimProgress.value = '${formatCount(n)} tries so far';
        }
      });
    } else {
      nonce = await compute(_grindInIsolate, {'tx': tx, 'bits': bits});
    }
    claimProgress.value = '';
    (tx['payload'] as Map<String, dynamic>)['work_nonce'] = nonce;
    await w.sign(tx);
    await node.sendTx(tx);
    return info;
  }

  Future<int> claimStarter(String name) async {
    final w = wallet!;
    final info = await _claim(TxType.claimStarter, {'name': name, 'kind': 'person', 'model_family': '', 'operator': '', 'description': '', 'enc_pub': w.encPub});
    return (info['starter_amount'] as int?) ?? 0;
  }

  Future<int> claimGrant(EarnedGrant g) async {
    await _claim(TxType.claimGrant, {'tier': g.tier});
    return g.amount;
  }

  Future<String> send(String to, int amountSeeds, String memo) async {
    final w = wallet!;
    if (!isValidAddress(to)) throw ArgumentError('that is not a BerryChain address');
    final tx = buildTx(TxType.transfer, w.address, await node.nextNonce(w.address), minFee, {'to': to, 'amount': amountSeeds, 'memo': memo}, Network.chainId);
    await w.sign(tx);
    return node.sendTx(tx);
  }

  /// One sealed copy to every member of [group]. Each copy carries the group
  /// inside its envelope so the others can reply to everyone. Returns the ids.
  Future<List<String>> sendGroupLetter(LetterGroup group, String subject, String body, int amountSeeds, {String? replyTo, Uint8List? photoJpeg}) async {
    final me = wallet!.address;
    final targets = group.members.where((m) => m != me).toList();
    if (targets.isEmpty) throw ArgumentError('the crew has nobody in it but you');
    for (final t in targets) {
      if (!await canReceiveLetters(t)) throw ArgumentError('${await lookupName(t)} (${t.substring(0, 12)}…) has no receiving key yet; remove them from the crew or wait until they claim a starter');
    }
    final fee = letterFee ?? minFee;
    final need = targets.length * (fee + amountSeeds);
    if ((balance ?? 0) < need) throw ArgumentError('${targets.length} letters need ${formatBerry(need)} BERRY and you have ${formatBerry(balance ?? 0)}');
    final ids = <String>[];
    for (final t in targets) {
      ids.add(await sendLetter(t, subject, body, amountSeeds, replyTo: replyTo, photoJpeg: photoJpeg, group: group));
    }
    return ids;
  }

  Future<String> sendLetter(String to, String subject, String body, int amountSeeds, {String? replyTo, Uint8List? photoJpeg, LetterGroup? group}) async {
    final w = wallet!;
    if (!isValidAddress(to)) throw ArgumentError('that is not a BerryChain address');
    if (to == w.address) throw ArgumentError('that is your own address');
    final acct = await node.account(to);
    final reg = acct['llm'] as Map<String, dynamic>?;
    final encPub = reg?['enc_pub'] as String?;
    if (encPub == null) throw ArgumentError('that address has not claimed a starter yet, so it has no receiving key');
    final plain = composeLetter(body, subject: subject, replyTo: replyTo, senderName: w.label, photoJpeg: photoJpeg, group: group);
    if (!fitsEnvelope(plain)) throw ArgumentError('the letter is too long for one envelope; shorten it or drop the picture');
    final key = newPacketKey();
    final ct = await encryptPacket(key, plain);
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

String formatCount(int n) {
  final s = n.toString();
  final out = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) out.write(',');
    out.write(s[i]);
  }
  return out.toString();
}

int _grindInIsolate(Map<String, dynamic> args) =>
    grindClaim(Map<String, dynamic>.from(args['tx'] as Map), args['bits'] as int);
