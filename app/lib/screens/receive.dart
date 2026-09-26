import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:share_plus/share_plus.dart';

import '../session.dart';

import '../main.dart';
import 'common.dart';

/// Opens the phone's share sheet with a ready-made note: what BerryChain is,
/// where to get the app, and this wallet's address to write to.
Future<void> shareInvite(BuildContext context) async {
  final s = SessionScope.of(context);
  final w = s.wallet!;
  final name = (s.registry?['name'] as String?) ?? '';
  await SharePlus.instance.share(ShareParams(text: Network.invite(w.address, name), subject: 'Write to me on BerryChain'));
}

class ReceiveScreen extends StatelessWidget {
  const ReceiveScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final w = SessionScope.of(context).wallet!;
    return Scaffold(
      appBar: AppBar(title: const Text('Receive')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Center(
            child: Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12)),
              child: QrImageView(data: w.address, size: 220, backgroundColor: Colors.white),
            ),
          ),
          const SizedBox(height: 18),
          const Text('YOUR ADDRESS', style: TextStyle(fontSize: 11.5, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: Color(0xFF6F7883))),
          const SizedBox(height: 6),
          SelectableText(w.address, style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
          const SizedBox(height: 14),
          FilledButton.icon(icon: const Icon(Icons.copy), label: const Text('Copy address'), onPressed: () => copyToClipboard(context, w.address, what: 'Address copied')),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            icon: const Icon(Icons.ios_share),
            label: const Text('Tell a friend'),
            onPressed: () => shareInvite(context),
          ),
          const SizedBox(height: 18),
          const Text('Give this to anyone who wants to send you BERRY or a letter. Coins arrive whether or not the app is open; the chain holds them for you.', style: TextStyle(height: 1.4)),
          const SizedBox(height: 14),
          const Text('RECEIVING KEY', style: TextStyle(fontSize: 11.5, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: Color(0xFF6F7883))),
          const SizedBox(height: 6),
          SelectableText(w.encPub, style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
          const SizedBox(height: 6),
          const Text('Only needed if you have not claimed a starter or registered: a sender can seal a letter to this key directly. Safe to share.', style: TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
        ],
      ),
    );
  }
}
