import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/units.dart';
import '../main.dart';
import '../session.dart';
import 'claim.dart';
import 'common.dart';
import 'contacts.dart';
import 'letters.dart';
import 'receive.dart';
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
    final amount = await runBusy(context, 'Working for your ${g.title.toLowerCase()}. The phone hashes for a little while. Keep the app open.', () => s.claimGrant(g), progress: s.claimProgress);
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
        final grants = s.earnedGrants;
        final total = s.inbox.length + s.sent.length;
        final unread = s.unreadCount;
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
                // ---- masthead: the same top as the website
                Container(
                  padding: const EdgeInsets.fromLTRB(16, 18, 16, 16),
                  decoration: BoxDecoration(color: Palette.sea, borderRadius: BorderRadius.circular(14)),
                  child: Column(
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          SvgPicture.asset('assets/icons/berry-gold.svg', height: 34),
                          const SizedBox(width: 10),
                          const Text('BerryChain', style: TextStyle(color: Colors.white, fontSize: 26, fontWeight: FontWeight.w700, letterSpacing: -0.3)),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          SvgPicture.asset('assets/icons/skull.svg', height: 18),
                          const SizedBox(width: 8),
                          const Flexible(child: Text("Privacy is not dead in the water, it's back.", textAlign: TextAlign.center, style: TextStyle(color: Palette.gold, fontStyle: FontStyle.italic, fontSize: 14.5))),
                          const SizedBox(width: 8),
                          SvgPicture.asset('assets/icons/skull.svg', height: 18),
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 10),
                // ---- balance with the berry symbol as a currency sign
                Tile(
                  label: 'Balance',
                  trailing: s.busy ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)) : null,
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      SvgPicture.asset('assets/icons/berry.svg', height: 30),
                      const SizedBox(width: 8),
                      Expanded(child: Text(bal == null ? '–' : formatBerry(bal), style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w600))),
                    ],
                  ),
                ),
                if (mismatch)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 4),
                    child: Text('The two seed nodes disagree about this balance. One may be behind; pull to refresh in a minute.', style: TextStyle(color: Palette.band)),
                  ),
                if (s.lastError != null)
                  Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Text(s.lastError!, style: const TextStyle(color: Palette.band))),
                if (s.lastNote != null)
                  Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Text(s.lastNote!, style: const TextStyle(color: Palette.leaf, fontSize: 13))),
                const SizedBox(height: 4),
                // ---- letters: the main thing, so it sits high
                FilledButton(
                  style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(60), backgroundColor: Palette.gold, foregroundColor: Palette.sea),
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const LettersScreen())),
                  child: Row(
                    children: [
                      const Icon(Icons.mail_outline, size: 26),
                      const SizedBox(width: 12),
                      const Expanded(child: Text('Letters', style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700))),
                      _Count(label: 'total', value: total),
                      const SizedBox(width: 8),
                      _Count(label: 'unread', value: unread, highlight: unread > 0),
                    ],
                  ),
                ),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  icon: const Icon(Icons.people_outline),
                  label: Text(s.contacts.isEmpty ? 'Contacts' : 'Contacts (${s.contacts.length})'),
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ContactsScreen())),
                ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  icon: SvgPicture.asset('assets/icons/cannon.svg', height: 22),
                  label: const Text('Share BerryChain with a friend'),
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ReceiveScreen())),
                ),
                const SizedBox(height: 10),
                if (s.registry == null && bal != null)
                  Card(
                    color: const Color(0xFFFBF1DC),
                    child: ListTile(
                      leading: const Icon(Icons.card_giftcard, color: Palette.brass),
                      title: const Text('Claim your starter'),
                      subtitle: Text('${s.starterAmount == null ? 'Some' : formatBerry(s.starterAmount!)} BERRY from the treasury, plus a name so people can write to you. Once per chest.'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ClaimScreen())),
                    ),
                  ),
                if (s.registry != null && !s.holdsCurrentKey)
                  Card(
                    color: const Color(0xFFFBE4DC),
                    child: ListTile(
                      leading: const Icon(Icons.key_off_outlined, color: Palette.band),
                      title: const Text('Your receiving key is not on this phone'),
                      subtitle: const Text('It was rotated elsewhere without a backup. New letters cannot be read here until you rotate. Open Settings to do it.'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SettingsScreen())),
                    ),
                  ),
                // ---- bonus berries (the correspondent grants)
                if (s.registry != null)
                  Card(
                    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(12)), side: BorderSide(color: Color(0xFFDCCFB4))),
                    child: Container(
                      decoration: const BoxDecoration(border: Border(top: BorderSide(color: Palette.gold, width: 3)), borderRadius: BorderRadius.vertical(top: Radius.circular(12))),
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(children: [
                            SvgPicture.asset('assets/icons/chest.svg', height: 22),
                            const SizedBox(width: 8),
                            const Text('BONUS BERRIES', style: TextStyle(fontSize: 11.5, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: Color(0xFF6F7883))),
                          ]),
                          const SizedBox(height: 6),
                          Text('${s.correspondents}', style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w600)),
                          const SizedBox(height: 2),
                          Text(s.seatsLive
                              ? 'Write to new people and have them write back to get bonus berry grants. Founding seats are given by the harbour\'s registrars: apply with a letter once you have three pen pals.'
                              : 'Write to new people and have them write back to get bonus berry grants.', style: const TextStyle(fontSize: 13, color: Color(0xFF6F7883))),
                          const SizedBox(height: 8),
                          for (final g in grants)
                            Padding(
                              padding: const EdgeInsets.symmetric(vertical: 3),
                              child: Row(
                                children: [
                                  Icon(g.taken ? Icons.check_circle : (s.correspondents >= g.need ? Icons.stars : Icons.radio_button_unchecked),
                                      size: 20, color: g.taken ? Palette.leaf : (s.correspondents >= g.need ? Palette.brass : const Color(0xFF9A8D94))),
                                  const SizedBox(width: 8),
                                  Expanded(child: Text('${g.title}: ${formatBerry(g.amount)} BERRY at ${g.need} people', style: const TextStyle(fontSize: 14))),
                                  if (!g.taken && s.correspondents >= g.need && !(g.tier == 'founding' && s.seatsLive))
                                    TextButton(onPressed: () => claim(g), child: const Text('Claim')),
                                  if (!g.taken && s.correspondents >= g.need && g.tier == 'founding' && s.seatsLive)
                                    TextButton(
                                      onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ComposeScreen(
                                          to: Network.harbourmaster, subject: 'Founding seat application'))),
                                      child: const Text('Apply'),
                                    ),
                                ],
                              ),
                            ),
                        ],
                      ),
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
                    trailing: IconButton(icon: const Icon(Icons.ios_share), tooltip: 'Share BerryChain with a friend', onPressed: () => shareInvite(context)),
                  ),
                ),
                Tile(
                  label: 'Your address',
                  trailing: IconButton(icon: const Icon(Icons.copy, size: 20), onPressed: () => copyToClipboard(context, w.address, what: 'Address copied')),
                  child: Text(w.address, style: const TextStyle(fontFamily: 'monospace', fontSize: 12.5)),
                ),
                if (s.registry != null)
                  Tile(
                    label: 'Registered as',
                    trailing: (s.registry!['founding'] as bool? ?? false)
                        ? const Chip(label: Text('Founder'), backgroundColor: Color(0xFFFBF1DC), side: BorderSide(color: Palette.gold))
                        : null,
                    child: Text('${s.registry!['name']}', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
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
                const SizedBox(height: 10),
                Center(
                  child: TextButton.icon(
                    icon: const Icon(Icons.open_in_new, size: 15),
                    label: const Text('berrychain.link', style: TextStyle(fontSize: 13)),
                    style: TextButton.styleFrom(foregroundColor: Palette.brass, padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4)),
                    onPressed: () => launchUrl(Uri.parse(Network.site), mode: LaunchMode.externalApplication),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _Count extends StatelessWidget {
  final String label;
  final int value;
  final bool highlight;
  const _Count({required this.label, required this.value, this.highlight = false});
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: highlight ? Palette.band : Palette.sea.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(14)),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('$value', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: highlight ? Colors.white : Palette.sea)),
            Text(label, style: TextStyle(fontSize: 10, color: highlight ? Colors.white : Palette.sea)),
          ],
        ),
      );
}
