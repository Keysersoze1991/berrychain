import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'crypto.dart';
import 'node.dart';

/// The parcel room: large attachments sealed on the phone, kept beside the
/// chain by a seed, paid for with an ordinary transfer whose memo names the
/// parcel's hash. The room never sees the key; it rides inside the letter.
/// Mirrors berrychain/parcels.py.
const parcelMemoPrefix = 'parcel:';

/// What a room charges and allows, read from GET /parcels/status.
class ParcelTerms {
  final String room, address;
  final int maxBytes, chunkBytes, pricePerChunk, ttlDays;
  ParcelTerms(this.room, this.address, this.maxBytes, this.chunkBytes, this.pricePerChunk, this.ttlDays);

  int priceFor(int size) {
    final chunks = size <= 0 ? 1 : (size + chunkBytes - 1) ~/ chunkBytes;
    return (chunks < 1 ? 1 : chunks) * pricePerChunk;
  }
}

/// The reference carried inside a sealed letter.
class ParcelRef {
  final String hash, key, name, room;
  final int size;
  ParcelRef({required this.hash, required this.key, required this.size, required this.name, required this.room});

  Map<String, dynamic> toJson() => {'hash': hash, 'key': key, 'size': size, 'name': name, 'room': room};

  static ParcelRef? fromJson(Object? o) {
    if (o is! Map || o['hash'] is! String || o['key'] is! String) return null;
    return ParcelRef(
        hash: o['hash'] as String,
        key: o['key'] as String,
        size: (o['size'] as num?)?.toInt() ?? 0,
        name: ((o['name'] as String?) ?? 'parcel').trim().isEmpty ? 'parcel' : (o['name'] as String).substring(0, (o['name'] as String).length > 120 ? 120 : (o['name'] as String).length),
        room: (o['room'] as String?) ?? '');
  }
}

String roomFor(String nodeUrl) => nodeUrl.replaceFirst(RegExp(r'/+$'), '');

Future<ParcelTerms> parcelTerms(String room, {http.Client? client}) async {
  final c = client ?? http.Client();
  final r = await c.get(Uri.parse('${roomFor(room)}/parcels/status')).timeout(const Duration(seconds: 20));
  if (r.statusCode != 200) throw NodeError('the parcel room at $room is not answering (${r.statusCode})');
  final j = jsonDecode(r.body) as Map<String, dynamic>;
  return ParcelTerms(roomFor(room), j['address'] as String, j['max_bytes'] as int, j['chunk_bytes'] as int, j['price_per_chunk'] as int, (j['ttl_days'] as int?) ?? 30);
}

/// Seal [data] with a fresh key: returns (key, ciphertext, hash).
Future<(Uint8List, Uint8List, String)> sealParcel(Uint8List data) async {
  final key = newPacketKey();
  final ct = await encryptPacket(key, data);
  return (key, ct, toHex(sha256(ct)));
}

/// Hand the sealed bytes to the room. Returns the room's status line.
Future<String> uploadParcel(String room, String hash, Uint8List ciphertext, {http.Client? client}) async {
  final c = client ?? http.Client();
  final r = await c
      .post(Uri.parse('${roomFor(room)}/parcels/$hash'), headers: {'Content-Type': 'application/octet-stream'}, body: ciphertext)
      .timeout(const Duration(minutes: 5));
  final j = jsonDecode(r.body) as Map<String, dynamic>;
  if (r.statusCode >= 400) throw NodeError('the parcel room refused the upload: ${j['error']}');
  return (j['status'] as String?) ?? '';
}

/// Fetch, check the hash, open with the letter's key.
Future<Uint8List> fetchParcel(ParcelRef ref, {http.Client? client}) async {
  final c = client ?? http.Client();
  final r = await c.get(Uri.parse('${roomFor(ref.room)}/parcels/${ref.hash}')).timeout(const Duration(minutes: 5));
  if (r.statusCode != 200) {
    String why = 'not there any more';
    try {
      why = (jsonDecode(r.body) as Map)['error'] as String? ?? why;
    } catch (_) {}
    throw NodeError('the parcel could not be fetched: $why');
  }
  if (toHex(sha256(r.bodyBytes)) != ref.hash) throw NodeError('the parcel room served bytes that do not match the letter');
  return decryptPacket(fromHex(ref.key), r.bodyBytes);
}

/// Ask the room to drop a parcel this wallet paid for.
Future<bool> deleteParcel(ParcelRef ref, String address, String signPriv, String signPub, {http.Client? client}) async {
  final c = client ?? http.Client();
  final ts = DateTime.now().millisecondsSinceEpoch ~/ 1000;
  final sig = await sign(signPriv, 'berrychain-parcel|delete|${ref.hash}|$address|$ts'.codeUnits);
  final req = http.Request('DELETE', Uri.parse('${roomFor(ref.room)}/parcels/${ref.hash}'))
    ..headers['Content-Type'] = 'application/json'
    ..body = jsonEncode({'pub': signPub, 'ts': ts, 'sig': sig});
  final r = await c.send(req).timeout(const Duration(seconds: 30));
  final body = await r.stream.bytesToString();
  try {
    return (jsonDecode(body) as Map)['ok'] == true;
  } catch (_) {
    return false;
  }
}

String formatBytes(int n) {
  if (n < 1024) return '$n bytes';
  if (n < 1024 * 1024) return '${(n / 1024).toStringAsFixed(n < 10 * 1024 ? 1 : 0)} KB';
  return '${(n / (1024 * 1024)).toStringAsFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB';
}
