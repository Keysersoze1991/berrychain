import 'package:flutter/material.dart';

import 'screens/home.dart';
import 'screens/unlock.dart';
import 'screens/welcome.dart';
import 'session.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(BerryApp(Session()));
}

/// Shown in Settings and on the welcome screen; keep in step with pubspec.yaml.
const appVersion = '0.7.0';

/// The chain's palette: open-water navy, straw gold, parchment.
class Palette {
  static const sea = Color(0xFF0C1F33);
  static const sea2 = Color(0xFF123252);
  static const gold = Color(0xFFD9A62B);
  static const gold2 = Color(0xFFF0C453);
  static const parchment = Color(0xFFF6F0E3);
  static const ink = Color(0xFF1B2430);
  static const brass = Color(0xFF8A6516);
  static const band = Color(0xFFC2382B);
  static const leaf = Color(0xFF2F7A4B);
}

class BerryApp extends StatefulWidget {
  final Session session;
  const BerryApp(this.session, {super.key});
  @override
  State<BerryApp> createState() => _BerryAppState();
}

class _BerryAppState extends State<BerryApp> {
  bool ready = false;

  @override
  void initState() {
    super.initState();
    widget.session.init().then((_) => setState(() => ready = true));
  }

  @override
  Widget build(BuildContext context) {
    final scheme = ColorScheme.fromSeed(seedColor: Palette.sea, primary: Palette.sea, secondary: Palette.gold, surface: Palette.parchment, brightness: Brightness.light);
    return SessionScope(
      session: widget.session,
      child: MaterialApp(
        title: 'BerryChain',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          colorScheme: scheme,
          scaffoldBackgroundColor: Palette.parchment,
          appBarTheme: const AppBarTheme(backgroundColor: Palette.sea, foregroundColor: Colors.white, elevation: 0),
          filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(backgroundColor: Palette.sea, foregroundColor: Palette.gold2, minimumSize: const Size.fromHeight(48))),
          outlinedButtonTheme: OutlinedButtonThemeData(style: OutlinedButton.styleFrom(foregroundColor: Palette.ink, minimumSize: const Size.fromHeight(48))),
          inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder(), filled: true, fillColor: Colors.white),
          cardTheme: const CardThemeData(color: Color(0xFFFFFAF0), elevation: 1, margin: EdgeInsets.symmetric(vertical: 6)),
          useMaterial3: true,
        ),
        home: !ready
            ? const Scaffold(body: Center(child: CircularProgressIndicator()))
            : ListenableBuilder(
                listenable: widget.session,
                builder: (context, _) {
                  final s = widget.session;
                  if (s.wallet != null) return const HomeScreen();
                  if (s.hasWalletFile) return const UnlockScreen();
                  return const WelcomeScreen();
                },
              ),
      ),
    );
  }
}

/// Makes the session reachable from any screen: `Session.of(context)`.
class SessionScope extends InheritedWidget {
  final Session session;
  const SessionScope({super.key, required this.session, required super.child});
  static Session of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<SessionScope>()!.session;
  @override
  bool updateShouldNotify(SessionScope old) => old.session != session;
}
