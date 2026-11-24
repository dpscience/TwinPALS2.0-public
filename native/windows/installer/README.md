# Windows installer

The public entry point is `scripts/build-release.ps1`. Inno Setup compiles `TwinPALS.iss` against an include generated from the verified portable manifest. The installer ships the desktop, MCP server, datasets and legal notices together. The small installed-layout marker selects the per-user data path on both launchers.

Choose **English** or **Deutsch** when Setup opens. For a scripted launch, pass `/LANG=english` or `/LANG=german` to the same EXE.

## Verify a release candidate

Use a Windows test account without a registered TwinPALS installer. Supply a new directory for evidence and disposable data.

```powershell
.venv\Scripts\python.exe scripts/verify_installer.py --setup dist/TwinPALS-2.0.0-windows-x64-setup.exe --work tmp/installer-lifecycle
```

The test exercises the final EXE, checks installed hashes, opens the desktop, creates a custom database entry, connects an MCP client and checks the study queue. It then verifies repair, upgrade from a minimal earlier-version fixture, downgrade refusal, active-service protection, uninstall and reinstall. The resulting JSON identifies the tested installer by SHA-256.

Keep the AppId stable. When retiring program files in a future update, name obsolete publisher-owned paths individually. Supply the preceding public EXE with `--previous-setup` to test that actual version transition. Keep a user-created file in the verification corpus. Setup refuses an unrelated nonempty target directory; after uninstall, users who kept personal files in that directory may select another empty program folder and still access their original data.

Before publishing, sign the intended binaries if a signing certificate is available, then test and hash the bytes that will actually be uploaded. Run prerequisite and cancellation checks on a clean Windows image whenever platform requirements change. The Microsoft bootstrapper URL and SHA-256 are pinned in the wizard script. An update to either needs a fresh check of the Microsoft Authenticode signature.

[Build instructions](../../../docs/BUILD.md) · [Data and release procedure](../../../docs/PORTABLE_RELEASE.md)

