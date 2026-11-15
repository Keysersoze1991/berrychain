import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// Thin client for a node's JSON API. Every call returns the decoded body; a
/// non-2xx answer becomes a [NodeError] carrying the node's message.
class NodeError implements Exception {
  final String message;
  final int? status;
  NodeError(this.message, [this.status]);
  @override
  String toString() => message;
}

class Node {
  final String url;
  final Duration timeout;
  final http.Client _http;
  // One client for every Node: they are made freely (one per seed, per check) and a client each was never closed.
  static final http.Client _shared = http.Client();
  Node(String url, {this.timeout = const Duration(seconds: 20), http.Client? client})
      : url = url.replaceFirst(RegExp(r'/+$'), ''),
        _http = client ?? _shared;

  Future<Map<String, dynamic>> get(String path) async {
    final http.Response r;
    try {
      r = await _http.get(Uri.parse('$url$path')).timeout(timeout);
    } catch (e) {
      throw NodeError('cannot reach $url: $e');
    }
    return _decode(r);
  }

  Future<Map<String, dynamic>> post(String path, Object body) async {
    final http.Response r;
    try {
      r = await _http
          .post(Uri.parse('$url$path'), headers: {'Content-Type': 'application/json'}, body: jsonEncode(body))
          .timeout(timeout);
    } catch (e) {
      throw NodeError('cannot reach $url: $e');
    }
    return _decode(r);
  }

  Map<String, dynamic> _decode(http.Response r) {
    Object? d;
    try {
      d = jsonDecode(utf8.decode(r.bodyBytes));
    } catch (_) {
      d = null;
    }
    if (r.statusCode < 200 || r.statusCode >= 300) {
      final msg = (d is Map && d['error'] != null) ? d['error'].toString() : 'node answered ${r.statusCode}';
      throw NodeError(msg, r.statusCode);
    }
    if (d is! Map<String, dynamic>) throw NodeError('unexpected answer from the node');
    return d;
  }

  // ------------------------------------------------------------ queries
  Future<Map<String, dynamic>> status() => get('/status');
  Future<Map<String, dynamic>> params() => get('/params');
  Future<Map<String, dynamic>> account(String address) => get('/account/$address');
  /// Every receiving key an account has published, with rotation backups.
  Future<Map<String, dynamic>> keys(String address) => get('/keys/$address');
  Future<Map<String, dynamic>> tx(String id) => get('/tx/$id');
  Future<Map<String, dynamic>> block(int height) => get('/block/$height');
  Future<Map<String, dynamic>> letter(String id) => get('/letter/$id');

  Future<List<Map<String, dynamic>>> headers(int from, int to) async =>
      ((await get('/headers?from=$from&to=$to'))['headers'] as List).cast<Map<String, dynamic>>();

  /// Letters on the chain; with [pending] also the ones still in the node's
  /// mempool (height null), so a letter shows the moment it reaches the seed.
  Future<List<Map<String, dynamic>>> letters({String? to, String? from, int? since, bool pending = false}) async {
    final q = <String>[
      if (to != null) 'to=$to',
      if (from != null) 'from=$from',
      if (since != null) 'since=$since',
      if (pending) 'pending=1',
    ].join('&');
    return ((await get('/letters${q.isEmpty ? '' : '?$q'}'))['letters'] as List).cast<Map<String, dynamic>>();
  }

  /// The nonce the next transaction from [address] must carry: confirmed
  /// plus anything already waiting in the node's mempool.
  Future<int> nextNonce(String address) async {
    final a = await account(address);
    return (a['next_nonce'] ?? a['nonce']) as int;
  }

  Future<String> sendTx(Map<String, dynamic> tx) async => (await post('/tx', tx))['txid'] as String;
}

/// Ask one of [count] interchangeable sources, starting with number [first]. When it fails, or has not answered
/// within [patience], the next one is asked as well, and so on round the list. The first answer wins and comes
/// back with the number of the source that gave it; when every source fails, the first failure is thrown.
Future<(int, T)> firstToAnswer<T>(int count, int first, Future<T> Function(int i) ask,
    {Duration patience = const Duration(seconds: 6)}) {
  final done = Completer<(int, T)>();
  Object? firstError;
  StackTrace? firstStack;
  var asked = 0, failed = 0;
  Timer? timer;
  void next() {
    timer?.cancel();
    if (done.isCompleted || asked >= count) return;
    final i = (first + asked) % count;
    asked++;
    if (asked < count) timer = Timer(patience, next);
    ask(i).then((v) {
      if (done.isCompleted) return;
      timer?.cancel();
      done.complete((i, v));
    }, onError: (Object e, StackTrace st) {
      firstError ??= e;
      firstStack ??= st;
      failed++;
      if (done.isCompleted) return;
      if (failed == count) {
        timer?.cancel();
        done.completeError(firstError!, firstStack);
      } else {
        next();
      }
    });
  }

  next();
  return done.future;
}
