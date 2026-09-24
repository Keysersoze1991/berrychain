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
  Node(String url, {this.timeout = const Duration(seconds: 20), http.Client? client})
      : url = url.replaceFirst(RegExp(r'/+$'), ''),
        _http = client ?? http.Client();

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
  Future<Map<String, dynamic>> tx(String id) => get('/tx/$id');
  Future<Map<String, dynamic>> block(int height) => get('/block/$height');
  Future<Map<String, dynamic>> letter(String id) => get('/letter/$id');

  Future<List<Map<String, dynamic>>> headers(int from, int to) async =>
      ((await get('/headers?from=$from&to=$to'))['headers'] as List).cast<Map<String, dynamic>>();

  Future<List<Map<String, dynamic>>> letters({String? to, String? from, int? since}) async {
    final q = <String>[
      if (to != null) 'to=$to',
      if (from != null) 'from=$from',
      if (since != null) 'since=$since',
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
