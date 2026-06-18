import 'package:flutter/material.dart';

/// Counts how many times its [child] subtree is (re)built within a fixed window,
/// so a responsiveness test can assert a tab does NOT rebuild-storm (a runaway
/// `notifyListeners`/`setState` loop blows the count) — bug #board-freeze §2(b).
///
/// The probe rebuilds exactly when its own `build` runs, which in an
/// [IndexedStack] shell happens whenever the wrapped tab subtree rebuilds. The
/// counter is read after pumping a known number of frames; a healthy, idle tab
/// settles to zero further rebuilds, a storming one grows unboundedly.
class RebuildProbe extends StatefulWidget {
  const RebuildProbe({super.key, required this.child, required this.counter});

  final Widget child;

  /// Shared mutable counter incremented on every build of this probe.
  final RebuildCounter counter;

  @override
  State<RebuildProbe> createState() => _RebuildProbeState();
}

class _RebuildProbeState extends State<RebuildProbe> {
  @override
  Widget build(BuildContext context) {
    widget.counter.value++;
    return widget.child;
  }
}

/// A boxed int the [RebuildProbe] increments, readable by the test. A class (not
/// a bare int) so the same instance is shared across rebuilds without a closure.
class RebuildCounter {
  int value = 0;

  /// Reset the count to start a fresh measurement window.
  void reset() => value = 0;
}
