/**
 * AryaOS V1 — Stage 17: Connector Adapter Factory
 *
 * Registers and binds Stage 17 real connector capability adapters
 * into Stage 15's AdapterRegistry.
 */

import { adapterRegistry } from './capabilityAdapter';
import { githubConnectorAdapter } from './githubConnectorAdapter';
import { googleDriveConnectorAdapter } from './googleDriveConnectorAdapter';

export class ConnectorAdapterFactory {
  private registered = false;

  public initializeAdapters(): void {
    if (this.registered) return;

    // Register real GitHub adapter for its capabilities
    adapterRegistry.registerAdapter('github.issue_read', githubConnectorAdapter);
    adapterRegistry.registerAdapter('github.issue_write', githubConnectorAdapter);

    // Register Google Drive adapter for read-only capabilities
    adapterRegistry.registerAdapter('google_drive.list_files', googleDriveConnectorAdapter);
    adapterRegistry.registerAdapter('google_drive.read_file', googleDriveConnectorAdapter);

    this.registered = true;
  }
}

export const connectorAdapterFactory = new ConnectorAdapterFactory();
// Automatically bind on import
connectorAdapterFactory.initializeAdapters();
