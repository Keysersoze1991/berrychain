import 'dart:convert';

import 'node.dart';
import 'store.dart';
import 'tx.dart';

/// Signed transactions waiting for a connection: this phone's own, and ones
/// carried for nearby pen pals. A letter is sealed and signed before it goes
/// in here, so a carrier can forward it but never read or change it.
class OutboxItem {
  final String id;
  final Map<String, dynamic> tx;
  final bool mine;       // signed on this phone (kept until the chain has it or rejects it)
  final int created;     // unix seconds, when this phone first held it
  int hops;              // how many phones have carried it before this one
  OutboxItem({required this.id, required this.tx, required this.mine, required this.created, this.hops = 0});

  Map<String, dynamic> toJson() => {'id': id, 'tx': tx, 'mine': mine, 'created': created, 'hops': hops};
  static OutboxItem fromJson(Map<String, dynamic> j) => OutboxItem(
      id: j['id'] as String, tx: Map<String, dynamic>.from(j['tx'] as Map), mine: (j['mine'] as bool?) ?? false,
      created: (j['created'] as int?) ?? 0, hops: (j['hops'] as int?) ?? 0);
}

class Outbox {
  static const maxItems = 300;
  static const maxAgeSeconds = 7 * 24 * 3600;
  static const maxTxBytes = 64 * 1024;
  static const maxHops = 12;
  static const fileName = 'outbox.json';

  final List<OutboxItem> items = [];
  String? _path;

  int get mineCount => items.where((i) => i.mine).length;
  int get carriedCount => items.where((i) => !i.mine).length;
  bool get isEmpty => items.isEmpty;
  bool has(String id) => items.any((i) => i.id == id);

  Future<void> load() async {
    _path = '${await storeDir()}$fileName';
    final raw = await readText(_path!);
    items.clear();
    if (raw == null) return;
    try {
      for (final j in (jsonDecode(raw) as List)) {
        items.add(OutboxItem.fromJson(Map<String, dynamic>.from(j as Map)));
      }
    } catch (_) {
      items.clear();
    }
    prune();
  }

  Future<void> save() async {
    try {
      _path ??= '${await storeDir()}$fileName';
      await writeText(_path!, jsonEncode(items.map((i) => i.toJson()).toList()));
    } catch (_) {}                      // no store (tests, or a phone with no writable dir): keep going in memory
  }

  /// Drop stale and surplus items; carried ones go first.
  void prune() {
    final now = DateTime.now().millisecondsSinceEpoch ~/ 1000;
    items.removeWhere((i) => !i.mine && now - i.created > maxAgeSeconds);
    while (items.length > maxItems) {
      final idx = items.indexWhere((i) => !i.mine);
      if (idx < 0) break;
      items.removeAt(idx);
    }
  }

  /// Queue a transaction signed on this phone.
  Future<void> addMine(Map<String, dynamic> tx) async {
    final id = txid(tx);
    if (has(id)) return;
    items.add(OutboxItem(id: id, tx: tx, mine: true, created: DateTime.now().millisecondsSinceEpoch ~/ 1000));
    await save();
  }

  /// Everything this phone is holding, for handing to a nearby phone.
  List<Map<String, dynamic>> toWire() => items.map((i) => {'tx': i.tx, 'hops': i.hops}).toList();

  /// Take in what a nearby phone handed over. Returns how many were new.
  /// Only well-formed, signed, modest-sized transactions are kept; nothing is
  /// ever executed here, only forwarded.
  Future<int> fromWire(List<dynamic> wire) async {
    var added = 0;
    final now = DateTime.now().millisecondsSinceEpoch ~/ 1000;
    for (final w in wire) {
      try {
        final m = Map<String, dynamic>.from(w as Map);
        final tx = Map<String, dynamic>.from(m['tx'] as Map);
        final hops = ((m['hops'] as int?) ?? 0) + 1;
        if (hops > maxHops) continue;
        if (!looksLikeTx(tx)) continue;
        if (jsonEncode(tx).length > maxTxBytes) continue;
        final id = txid(tx);
        if (has(id)) continue;
        items.add(OutboxItem(id: id, tx: tx, mine: false, created: now, hops: hops));
        added++;
      } catch (_) {}
    }
    if (added > 0) {
      prune();
      await save();
    }
    return added;
  }

  static bool looksLikeTx(Map<String, dynamic> tx) {
    for (final k in const ['type', 'from', 'nonce', 'fee', 'payload', 'chain_id', 'sig', 'pubkey']) {
      if (!tx.containsKey(k)) return false;
    }
    return tx['type'] is String && tx['from'] is String && (tx['from'] as String).startsWith('brry1') && tx['nonce'] is int && tx['sig'] is String && tx['payload'] is Map;
  }

  /// Try to hand everything to a node. Items the chain accepts leave; items
  /// it rejects outright leave too (a carried letter that someone else already
  /// submitted is the common case); items that cannot be delivered because
  /// the node is out of reach stay. Returns (sent, rejected).
  Future<(int, int)> drain(List<String> nodes, {Duration timeout = const Duration(seconds: 12)}) async {
    if (items.isEmpty) return (0, 0);
    var sent = 0, rejected = 0;
    final ordered = [...items.where((i) => i.mine), ...items.where((i) => !i.mine)];
    for (final item in ordered) {
      var delivered = false, unreachable = true;
      String? rejection;
      for (final url in nodes) {
        try {
          await Node(url, timeout: timeout).sendTx(item.tx);
          delivered = true;
          unreachable = false;
          break;
        } on NodeError catch (e) {
          if (e.status != null) {
            unreachable = false;
            rejection = e.message;
            if (!e.message.toLowerCase().contains('mempool') && !e.message.toLowerCase().contains('fee')) break;
          }
        } catch (_) {}
      }
      if (delivered) {
        items.remove(item);
        sent++;
      } else if (!unreachable && rejection != null) {
        // The chain said no. A carried letter was most likely delivered by another phone already; our own gets one note.
        items.remove(item);
        rejected++;
        if (item.mine) lastRejection = rejection;
      } else {
        break; // no node reachable: try again later
      }
    }
    if (sent + rejected > 0) await save();
    return (sent, rejected);
  }

  String? lastRejection;
}

/// Drain the outbox file from a context with no Session (the background task).
Future<void> drainOutboxFile(List<String> nodes) async {
  final box = Outbox();
  await box.load();
  if (box.isEmpty) return;
  await box.drain(nodes);
}
