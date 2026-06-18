import 'package:bard_pro/deep_link.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for the pure invite-token parser. No `app_links` platform channel
/// is touched (CLAUDE.md §9) — only [DeepLinkService.parseInviteToken].
void main() {
  group('parseInviteToken', () {
    test('extracts the token from the registry "invite" query key', () {
      final uri = Uri.parse('bard://invite?invite=tok-abc123');
      expect(DeepLinkService.parseInviteToken(uri), 'tok-abc123');
    });

    test('extracts the token from the "token" query key (brief shape)', () {
      final uri = Uri.parse('bard://invite?token=tok-xyz');
      expect(DeepLinkService.parseInviteToken(uri), 'tok-xyz');
    });

    test('prefers "invite" over "token" when both are present', () {
      final uri = Uri.parse('bard://invite?invite=primary&token=secondary');
      expect(DeepLinkService.parseInviteToken(uri), 'primary');
    });

    test('handles an https invite URL (web join link)', () {
      final uri = Uri.parse('https://join.bardllm.dev/join?invite=tok-web');
      expect(DeepLinkService.parseInviteToken(uri), 'tok-web');
    });

    test('url-decodes a percent-encoded token value', () {
      final uri = Uri.parse('bard://invite?invite=a%2Fb%2Bc');
      expect(DeepLinkService.parseInviteToken(uri), 'a/b+c');
    });

    test('trims surrounding whitespace', () {
      final uri = Uri.parse('bard://invite?invite=%20tok%20');
      expect(DeepLinkService.parseInviteToken(uri), 'tok');
    });

    test('returns null when no invite/token param is present', () {
      expect(DeepLinkService.parseInviteToken(Uri.parse('bard://invite')), isNull);
      expect(
        DeepLinkService.parseInviteToken(Uri.parse('bard://invite?other=1')),
        isNull,
      );
    });

    test('returns null for an empty/whitespace-only token value', () {
      expect(
        DeepLinkService.parseInviteToken(Uri.parse('bard://invite?invite=')),
        isNull,
      );
      expect(
        DeepLinkService.parseInviteToken(Uri.parse('bard://invite?invite=%20%20')),
        isNull,
      );
    });
  });
}
