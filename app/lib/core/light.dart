import 'dart:convert';
import 'store.dart';

import 'crypto.dart';
import 'node.dart';
import 'tx.dart' as t;

/// Header-only verification of a node's chain, the same rules the reference
/// light client applies: every header must link, hash correctly, follow the
/// difficulty schedule, respect the timestamp rules and satisfy its
/// proof-of-work; the chain must contain the pinned genesis and checkpoint;
/// and the client never moves to a lighter chain than the best it has seen.
///
/// A phone cannot keep every header forever, so this client keeps the total
/// work of everything it verified plus a window of recent headers. Older
/// blocks are verified on demand by fetching the headers between them and
/// the window and checking that they link and carry proof-of-work.
class VerifyError implements Exception {
  final String message;
  VerifyError(this.message);
  @override
  String toString() => message;
}

const headerFields = ['height', 'prev_hash', 'timestamp', 'target', 'merkle_root', 'nonce', 'hash'];
const maxFutureDrift = 2 * 60 * 60;
const _pageSize = 100; // MAX_HEADERS_PER_REQUEST on the node

class Profile {
  final String chainId;
  final int targetBlockTime, difficultyWindow, minConfirmations;
  final BigInt maxTarget;
  const Profile(this.chainId, this.targetBlockTime, this.difficultyWindow, this.maxTarget, this.minConfirmations);

  static final mainnet = Profile('berry-1', 60, 60, BigInt.one << 240, 6);
  static final devnet = Profile('berry-dev', 1, 20, BigInt.one << 252, 1);
  static Profile byChainId(String id) => id == 'berry-dev' ? devnet : mainnet;
}

String headerBytes(Map<String, dynamic> h) =>
    'berry|${h['height']}|${h['prev_hash']}|${h['timestamp']}|${h['target']}|${h['merkle_root']}|${h['nonce']}';

String blockHash(Map<String, dynamic> h) => toHex(sha256d(utf8.encode(headerBytes(h))));

BigInt hexToTarget(String h) => BigInt.parse(h, radix: 16);
String targetToHex(BigInt t) => t.toRadixString(16).padLeft(64, '0');
BigInt workForTarget(BigInt target) => (BigInt.one << 256) ~/ (target + BigInt.one);

bool powOk(Map<String, dynamic> h) => bigFromBytes(fromHex(h['hash'] as String)) < hexToTarget(h['target'] as String);

String merkleRoot(List<String> txids) {
  if (txids.isEmpty) return '00' * 32;
  var layer = txids.map(fromHex).toList();
  while (layer.length > 1) {
    if (layer.length.isOdd) layer.add(layer.last);
    layer = [for (var i = 0; i < layer.length; i += 2) sha256([...layer[i], ...layer[i + 1]])];
  }
  return toHex(layer[0]);
}

class LightClient {
  final Profile profile;
  final String genesisHash;
  final int? checkpointHeight;
  final String? checkpointHash;
  final String? path;
  final int window;

  /// Recent verified headers, contiguous, ending at the tip.
  List<Map<String, dynamic>> headers = [];
  BigInt work = BigInt.zero; // of everything verified up to the tip
  int windowStart = 0;

  LightClient(this.profile, this.genesisHash, {this.checkpointHeight, this.checkpointHash, this.path, this.window = 2880});

  int get height => headers.isEmpty ? -1 : headers.last['height'] as int;
  Map<String, dynamic>? get tip => headers.isEmpty ? null : headers.last;

  static Future<LightClient> open(Profile profile, String genesisHash,
      {int? checkpointHeight, String? checkpointHash, String? path, int window = 2880}) async {
    final lc = LightClient(profile, genesisHash, checkpointHeight: checkpointHeight, checkpointHash: checkpointHash, path: path, window: window);
    final saved = path == null ? null : await readText(path);
    if (saved != null) {
      try {
        final d = jsonDecode(saved) as Map<String, dynamic>;
        if (d['genesis_hash'] == genesisHash) {
          lc.headers = (d['headers'] as List).cast<Map<String, dynamic>>();
          lc.work = BigInt.parse(d['work'] as String);
          lc.windowStart = d['window_start'] as int;
        }
      } catch (_) {
        lc.headers = [];
      }
    }
    return lc;
  }

  Future<void> save() async {
    final p = path;
    if (p == null) return;
    await writeText(p, jsonEncode({'genesis_hash': genesisHash, 'headers': headers, 'work': work.toString(), 'window_start': windowStart}));
  }

  // --------------------------------------------------------------- rules
  BigInt targetAt(List<Map<String, dynamic>> hdrs, int height, int base) {
    // hdrs[i] is the header at height base + i
    if (height <= 0) return profile.maxTarget;
    final w = profile.difficultyWindow;
    final prev = hdrs[height - 1 - base];
    final prevTarget = hexToTarget(prev['target'] as String);
    if (height % w != 0 || height < w) return prevTarget;
    final first = hdrs[height - w - base];
    var actual = (prev['timestamp'] as int) - (first['timestamp'] as int);
    if (actual < 1) actual = 1;
    final expected = w * profile.targetBlockTime;
    actual = actual.clamp(expected ~/ 4, expected * 4);
    var next = prevTarget * BigInt.from(actual) ~/ BigInt.from(expected);
    if (next > profile.maxTarget) next = profile.maxTarget;
    if (next < BigInt.one) next = BigInt.one;
    return next;
  }

  int medianTimePast(List<Map<String, dynamic>> hdrs, int uptoHeight, int base) {
    final lo = (uptoHeight - 11) < 0 ? 0 : uptoHeight - 11;
    final ts = <int>[for (var h = lo; h < uptoHeight; h++) hdrs[h - base]['timestamp'] as int]..sort();
    return ts.isEmpty ? 0 : ts[ts.length ~/ 2];
  }

  /// Validate [hdr] as the block extending hdrs[..upto) (hdrs[0] is at height
  /// [base]). Needs at least the previous difficulty window of headers.
  void checkHeader(Map<String, dynamic> hdr, List<Map<String, dynamic>> hdrs, int upto, int base, int now) {
    for (final k in headerFields) {
      if (!hdr.containsKey(k)) throw VerifyError('header missing $k');
    }
    final h = hdr['height'];
    if (h is! int || h != base + upto) throw VerifyError('header height $h does not extend ${base + upto - 1}');
    if (hdr['prev_hash'] != hdrs[upto - 1]['hash']) throw VerifyError('prev_hash does not match tip');
    if (hdr['timestamp'] is! int || hdr['nonce'] is! int) throw VerifyError('timestamp and nonce must be integers');
    if ((hdr['timestamp'] as int) <= medianTimePast(hdrs, h, base)) throw VerifyError('timestamp not after median of previous blocks');
    if ((hdr['timestamp'] as int) > now + maxFutureDrift) throw VerifyError('timestamp too far in the future');
    final target = hdr['target'];
    if (target is! String || target.length != 64) throw VerifyError('malformed target');
    // the schedule needs the previous header, or the window's first header at a retarget
    final needs = (h % profile.difficultyWindow == 0 && h >= profile.difficultyWindow) ? h - profile.difficultyWindow : h - 1;
    if (needs >= base) {
      if (hexToTarget(target) != targetAt(hdrs, h, base)) throw VerifyError('wrong difficulty target');
    }
    if (hdr['hash'] is! String || blockHash(hdr) != hdr['hash']) throw VerifyError('hash does not match header');
    if (!powOk(hdr)) throw VerifyError('proof of work not satisfied');
  }

  // ---------------------------------------------------------------- sync
  /// Bring the verified chain up to the node's tip. Returns true if the tip
  /// changed. Throws if the node's chain is invalid, lighter than the best
  /// seen, on another genesis, or missing the checkpoint.
  Future<bool> sync(Node node, {int? now}) async {
    now ??= DateTime.now().millisecondsSinceEpoch ~/ 1000;
    final st = await node.status();
    if (st['chain_id'] != profile.chainId) throw VerifyError('node is on chain ${st['chain_id']}, expected ${profile.chainId}');
    final peerHeight = st['height'] as int;

    if (headers.isEmpty) {
      return _initialSync(node, peerHeight, now);
    }
    // find the last block we share, walking back within the window
    int? common;
    var h = height < peerHeight ? height : peerHeight, step = 1;
    while (true) {
      if (h < windowStart) break;
      final got = await node.headers(h, h);
      if (got.isNotEmpty && got[0]['hash'] == headers[h - windowStart]['hash']) {
        common = h;
        break;
      }
      if (h == windowStart) break;
      h = (h - step) < windowStart ? windowStart : h - step;
      step *= 2;
    }
    if (common == null) {
      throw VerifyError('node has reorganised deeper than this phone remembers; it is either lying or the network forked badly');
    }
    // work of what we keep
    var candidate = headers.sublist(0, common + 1 - windowStart);
    var candidateWork = work;
    for (final dropped in headers.sublist(common + 1 - windowStart)) {
      candidateWork -= workForTarget(hexToTarget(dropped['target'] as String));
    }
    var lo = common + 1;
    final base = windowStart;
    while (lo <= peerHeight) {
      final hi = (lo + _pageSize - 1) < peerHeight ? lo + _pageSize - 1 : peerHeight;
      final page = await node.headers(lo, hi);
      if (page.isEmpty) break;
      for (final hdr in page) {
        checkHeader(hdr, candidate, candidate.length, base, now);
        candidate.add(hdr);
        candidateWork += workForTarget(hexToTarget(hdr['target'] as String));
      }
      lo = hi + 1;
    }
    if (candidateWork < work) throw VerifyError('node is on a lighter chain (height ${candidate.last['height']}) than the best already verified (height $height)');
    if (candidateWork == work && candidate.last['hash'] != tip!['hash']) throw VerifyError('node is on a different fork of equal work; keeping the chain already verified');
    _checkCheckpoint(candidate, base);
    final changed = candidate.last['hash'] != tip!['hash'];
    headers = candidate;
    work = candidateWork;
    _trim();
    if (changed) await save();
    return changed;
  }

  Future<bool> _initialSync(Node node, int peerHeight, int now) async {
    final b0 = await node.headers(0, 0);
    if (b0.isEmpty || b0[0]['hash'] != genesisHash || blockHash(b0[0]) != genesisHash) {
      throw VerifyError('node is not on the BerryChain genesis');
    }
    final all = <Map<String, dynamic>>[b0[0]];
    var w = BigInt.zero;
    var lo = 1;
    while (lo <= peerHeight) {
      final hi = (lo + _pageSize - 1) < peerHeight ? lo + _pageSize - 1 : peerHeight;
      final page = await node.headers(lo, hi);
      if (page.isEmpty) break;
      for (final hdr in page) {
        checkHeader(hdr, all, all.length, 0, now);
        all.add(hdr);
        w += workForTarget(hexToTarget(hdr['target'] as String));
      }
      lo = hi + 1;
    }
    _checkCheckpoint(all, 0);
    headers = all;
    work = w;
    windowStart = 0;
    _trim();
    await save();
    return true;
  }

  void _checkCheckpoint(List<Map<String, dynamic>> hdrs, int base) {
    final ch = checkpointHeight, chash = checkpointHash;
    if (ch == null || chash == null) return;
    if (ch < base) return; // below the window: it was checked when first synced
    if (hdrs.length <= ch - base || hdrs[ch - base]['hash'] != chash) {
      throw VerifyError('node\'s chain does not contain the pinned checkpoint at $ch');
    }
  }

  void _trim() {
    // keep the window plus a difficulty window of context for target checks
    final keep = window + profile.difficultyWindow + 12;
    if (headers.length > keep) {
      headers = headers.sublist(headers.length - keep);
      windowStart = headers.first['height'] as int;
    }
  }

  // -------------------------------------------------------------- verify
  /// The verified header at [h], fetching and link-checking older ones back
  /// from the window when [h] is below it.
  Future<Map<String, dynamic>> headerAt(Node node, int h) async {
    if (h < 0 || h > height) throw VerifyError('height $h is beyond the verified chain');
    if (h >= windowStart) return headers[h - windowStart];
    // walk from the window's first header back to h, checking each link
    var anchor = headers.first;
    var lo = h, hi = windowStart - 1;
    final chain = <Map<String, dynamic>>[];
    while (hi >= lo) {
      final from = (hi - _pageSize + 1) > lo ? hi - _pageSize + 1 : lo;
      final page = await node.headers(from, hi);
      if (page.length != hi - from + 1) throw VerifyError('node did not serve headers $from..$hi');
      chain.insertAll(0, page);
      hi = from - 1;
    }
    for (var i = chain.length - 1; i >= 0; i--) {
      final hdr = chain[i];
      if (blockHash(hdr) != hdr['hash'] || !powOk(hdr)) throw VerifyError('node served a bad header at ${hdr['height']}');
      if (anchor['prev_hash'] != hdr['hash'] || (anchor['height'] as int) != (hdr['height'] as int) + 1) {
        throw VerifyError('header ${hdr['height']} does not link to the verified chain');
      }
      anchor = hdr;
    }
    return chain.first;
  }

  /// Prove [id] is in a block on the verified chain with at least
  /// [minConfirmations] blocks on top (its own block counts as one).
  /// Returns the transaction exactly as the block carries it.
  Future<Map<String, dynamic>> verifyTx(Node node, String id, {int? minConfirmations}) async {
    minConfirmations ??= profile.minConfirmations;
    final Map<String, dynamic> r;
    try {
      r = await node.tx(id);
    } on NodeError catch (e) {
      if (e.status == 404) throw VerifyError('the node does not know this transaction');
      rethrow;
    }
    if (r['status'] != 'confirmed' || r['height'] is! int) throw VerifyError('transaction is not confirmed');
    final h = r['height'] as int;
    if (h <= 0 || h > height) throw VerifyError('transaction height is beyond the verified chain');
    if (height - h + 1 < minConfirmations) throw VerifyError('only ${height - h + 1} of $minConfirmations confirmations');
    final hdr = await headerAt(node, h);
    final blk = await node.block(h);
    if (blk['hash'] != hdr['hash'] || blockHash(blk) != hdr['hash']) throw VerifyError('block $h does not match the verified header');
    final txs = (blk['txs'] as List).cast<Map<String, dynamic>>();
    final ids = txs.map(t.txid).toList();
    if (merkleRoot(ids) != blk['merkle_root']) throw VerifyError('block $h merkle root does not match its transactions');
    final i = ids.indexOf(id);
    if (i < 0) throw VerifyError('transaction is not in block $h');
    return txs[i];
  }
}
