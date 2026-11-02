# Windows service with NSSM

Use NSSM (Non-Sucking Service Manager) to run the wrappers as services.

1. Download NSSM from https://nssm.cc and copy `nssm.exe` to `C:\Windows\System32`.
2. Create a service account with no write rights to the plant data.
3. Open an admin shell and install the runtime:

   ```
   nssm install CrosscutRuntime C:\Windows\System32\cmd.exe "/c C:\crosscut\deploy\windows\run-runtime.cmd"
   nssm set CrosscutRuntime ObjectName .\crosscut-svc <password>
   nssm set CrosscutRuntime AppDirectory C:\crosscut
   nssm set CrosscutRuntime AppEnvironmentExtra CROSSCUT_ROOT=C:\crosscut\data
   nssm set CrosscutRuntime Start SERVICE_AUTO_START
   nssm start CrosscutRuntime
   ```

4. Repeat for the API with `CrosscutAPI` and `run-api.cmd`.
5. Check status with `nssm status CrosscutRuntime`, or `sc query CrosscutAPI`.

The wrappers already restart on exit, so set NSSM's own restart to "on failure" only
as a backup (`nssm set CrosscutRuntime AppExit Default Restart`).
Keep the password out of files; NSSM stores it in the service registry entry.
