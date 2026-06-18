import 'package:bard_pro/config.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for the config layer (CLAUDE.md §1). The environment map is
/// injected so we exercise every precedence branch without touching real env
/// vars.
void main() {
  group('AppConfig.fromEnvironment', () {
    test('falls back to localhost defaults when env is empty', () {
      final cfg = AppConfig.fromEnvironment(const {});
      expect(cfg.routerBaseUrl, AppConfig.defaultRouterBaseUrl);
      expect(cfg.registryBaseUrl, AppConfig.defaultRegistryBaseUrl);
      expect(cfg.authToken, isEmpty);
    });

    test('reads overrides from the environment', () {
      final cfg = AppConfig.fromEnvironment(const {
        AppConfig.routerUrlKey: 'https://router.example:8443',
        AppConfig.registryUrlKey: 'https://registry.example:8081',
        AppConfig.tokenKey: 'tok-123',
      });
      expect(cfg.routerBaseUrl, 'https://router.example:8443');
      expect(cfg.registryBaseUrl, 'https://registry.example:8081');
      expect(cfg.authToken, 'tok-123');
    });

    test('trims surrounding whitespace', () {
      final cfg = AppConfig.fromEnvironment(const {
        AppConfig.routerUrlKey: '  https://r.example  ',
        AppConfig.tokenKey: '  spaced-token  ',
      });
      expect(cfg.routerBaseUrl, 'https://r.example');
      expect(cfg.authToken, 'spaced-token');
    });

    test('treats a blank (whitespace-only) value as unset and uses the default', () {
      final cfg = AppConfig.fromEnvironment(const {
        AppConfig.routerUrlKey: '   ',
      });
      expect(cfg.routerBaseUrl, AppConfig.defaultRouterBaseUrl);
    });

    test('reads the process environment when no map is passed', () {
      // No assertion on the value (it varies per machine); this exercises the
      // Platform.environment fallback branch and must not throw.
      final cfg = AppConfig.fromEnvironment();
      expect(cfg.routerBaseUrl, isNotEmpty);
      expect(cfg.registryBaseUrl, isNotEmpty);
    });
  });

  group('AppConfig.resolve precedence', () {
    test('a non-blank runtime value wins over define and fallback', () {
      expect(AppConfig.resolve('runtime', 'define', 'fallback'), 'runtime');
    });

    test('a blank runtime value falls through to a non-blank define', () {
      expect(AppConfig.resolve('  ', 'define', 'fallback'), 'define');
      expect(AppConfig.resolve(null, 'define', 'fallback'), 'define');
    });

    test('blank runtime and blank define fall through to the fallback', () {
      expect(AppConfig.resolve(null, '   ', 'fallback'), 'fallback');
      expect(AppConfig.resolve('', '', 'fallback'), 'fallback');
    });

    test('trims the surviving value at each layer', () {
      expect(AppConfig.resolve('  runtime  ', '', ''), 'runtime');
      expect(AppConfig.resolve(null, '  define  ', ''), 'define');
    });
  });

  group('AppConfig.copyWith', () {
    const base = AppConfig(
      routerBaseUrl: 'r',
      registryBaseUrl: 'g',
      authToken: 't',
    );

    test('overrides only the named field', () {
      final next = base.copyWith(authToken: 't2');
      expect(next.routerBaseUrl, 'r');
      expect(next.registryBaseUrl, 'g');
      expect(next.authToken, 't2');
    });

    test('overrides all fields', () {
      final next = base.copyWith(
        routerBaseUrl: 'r2',
        registryBaseUrl: 'g2',
        authToken: 't2',
      );
      expect(next.routerBaseUrl, 'r2');
      expect(next.registryBaseUrl, 'g2');
      expect(next.authToken, 't2');
    });

    test('preserves all fields when no override is given', () {
      final next = base.copyWith();
      expect(next.routerBaseUrl, 'r');
      expect(next.registryBaseUrl, 'g');
      expect(next.authToken, 't');
    });
  });
}
