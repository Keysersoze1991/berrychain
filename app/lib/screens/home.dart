import 'package:flutter/material.dart';

import '../core/units.dart';
import '../main.dart';
import '../session.dart';
import 'claim.dart';
import 'common.dart';
import 'contacts.dart';
import 'letters.dart';
import 'receive.dart';
import 'send.dart';
import 'settings.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => SessionScope.of(context).refresh());
  }

  Future<void> claim(EarnedGrant g) async {
    final s = SessionScope.of(context);
    final amount = await runBusy(context, 'Working for your ${g.title.toLowerCase()}. The phone hashes for a little while. Keep the app open.', () => s.claimGrant(g));
    if (amount != null && mounted) {
      toast(context, '${formatBerry(amount)} BERRY on its way; it lands with the next block.');
      s.refresh();
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return ListenableBuilder(
      listenable: s,
      builder: (context, _) {
        final w = s.wallet!;
        final bal = s.balance;
        final mismatch = bal != null && s.balanceOther != null && s.balanceOther != bal;
        final unread = s.inbox.length;
        final grants = s.earnedGrants;
        return Scaffold(
          appBar: AppBar(
            title: Text(w.label.isEmpty ? 'BerryChain' : w.label),
            actions: [
              IconButton(icon: const Icon(Icons.settings_outlined), onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SettingsScreen()))),
              IconButton(icon: const Icon(Icons.lock_outline), tooltip: 'Lock', onPressed: s.lock),
            ],
          ),
          body: RefreshIndicator(
            onRefresh: s.refresh,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Tile(
                  label: 'Balance',
                  trailing: s.busy ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)) : null,
                  child: Text(bal == null ? '–' : '${formatBerry(bal)} BERRY', style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w600)),
                ),
                if (mismatch)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 4),
                    child: Text('The two seed nodes disagree about this balance. One may be behind; pull to refresh in a minute.', style: TextStyle(color: Palette.band)),
                  ),
                if (s.lastError != null)
                  Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Text(s.lastError!, style: const TextStyle(color: Palette.band))),
                Tile(
                  label: 'Your address',
                  trailing: IconButton(icon: const Icon(Icons.copy, size: 20), onPressed: () => copyToClipboard(context, w.address, what: 'Address copied')),
                  child: Text(w.address, style: const TextStyle(fontFamily: 'monospace', fontSize: 12.5)),
                ),
                if (s.registry == null && bal != null)
                  Card(
                    color: const Color(0xFFFBF1DC),
                    child: ListTile(
                      leading: const Icon(Icons.card_giftcard, color: Palette.brass),
                      title: const Text('Claim your starter'),
                      subtitle: Text('${s.starterAmount == null ? 'Some' : formatBerry(s.starterAmount!)} BERRY from the treasury, plus a name so people can write to you. Once per wallet.'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ClaimScreen())),
                    ),
                  ),
                if (s.registry != null)
                  Tile(
                    label: 'Registered as',
                    trailing: (s.registry!['founding'] as bool? ?? false)
                        ? const Chip(label: Text('Founder'), backgroundColor: Color(0xFFFBF1DC), side: BorderSide(color: Palette.gold))
                        : null,
                    child: Text('${s.registry!['name']}', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
                  ),
                if (s.registry != null)
                  Tile(
                    label: 'Correspondents',
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('${s.correspondents}', style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w600)),
                        const SizedBox(height: 2),
                        const Text('People you have written to who wrote back. Letters earn the grants below.', style: TextStyle(fontSize: 13, color: Color(0xFF6F7883))),
                        const SizedBox(height: 8),
                        for (final g in grants)
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 3),
                            child: Row(
                              children: [
                                Icon(g.taken ? Icons.check_circle : (s.correspondents >= g.need ? Icons.stars : Icons.radio_button_unchecked),
                                    size: 20, color: g.taken ? Palette.leaf : (s.correspondents >= g.need ? Palette.brass : const Color(0xFF9A8D94))),
                                const SizedBox(width: 8),
                                Expanded(child: Text('${g.title}: ${formatBerry(g.amount)} BERRY at ${g.need}', style: const TextStyle(fontSize: 14))),
                                if (!g.taken && s.correspondents >= g.need)
                                  TextButton(onPressed: () => claim(g), child: const Text('Claim')),
                              ],
                            ),
                          ),
                      ],
                    ),
                  ),
                Card(
                  color: const Color(0xFFEEF3F8),
                  child: ListTile(
                    leading: const Icon(Icons.anchor, color: Palette.brass),
                    title: const Text("The Harbourmaster's purse"),
                    subtitle: const Text(
                      'Write to the Harbourmaster and ${Network.welcomeTipBerry} BERRY rides back with his first reply. '
                      'Each week the best letter he receives wins ${Network.prizeBerry} BERRY. Mine your first block on a PC with this '
                      'address as the payout, and he sends ${Network.prizeBerry} BERRY more. The prizes shrink as the crew grows.',
                      style: TextStyle(height: 1.35),
                    ),
                    trailing: IconButton(icon: const Icon(Icons.ios_share), tooltip: 'Tell a friend', onPressed: () => shareInvite(context)),
                  ),
                ),
                const SizedBox(height: 8),
                Row(children: [
                  Expanded(child: FilledButton.icon(icon: const Icon(Icons.arrow_upward), label: const Text('Send'), onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SendScreen())))),
                  const SizedBox(width: 10),
                  Expanded(child: OutlinedButton.icon(icon: const Icon(Icons.qr_code_2), label: const Text('Receive'), onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ReceiveScreen())))),
                ]),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  icon: const Icon(Icons.people_outline),
                  label: Text(s.contacts.isEmpty ? 'People' : 'People (${s.contacts.length})'),
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ContactsScreen())),
                ),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  icon: const Icon(Icons.mail_outline),
                  label: Text(unread == 0 ? 'Letters' : 'Letters ($unread in your inbox)'),
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const LettersScreen())),
                ),
                const SizedBox(height: 18),
                Text(
                  s.nodeHeight == null
                      ? 'Not connected yet.'
                      : 'Node at block ${s.nodeHeight}. Verified in $deviceThe: ${s.verifiedHeight < 0 ? 'not yet' : 'block ${s.verifiedHeight}'}.',
                  style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13),
                ),
                const SizedBox(height: 4),
                const Text('BERRY has no price and no exchange. It is a unit of account on this network, nothing more.', style: TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
              ],
            ),
          ),
        );
      },
    );
  }
}
