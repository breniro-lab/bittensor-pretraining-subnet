import asyncio
from model.data import ModelMetadata
from model.model_tracker import ModelTracker
from model.storage.local_model_store import LocalModelStore
from model.storage.model_metadata_store import ModelMetadataStore
from model.storage.remote_model_store import RemoteModelStore


class ModelUpdater:
    """Checks if the currently tracked model for a hotkey matches what the miner committed to the chain."""

    def __init__(
        self,
        metadata_store: ModelMetadataStore,
        remote_store: RemoteModelStore,
        local_store: LocalModelStore,
        model_tracker: ModelTracker,
    ):
        self.metadata_store = metadata_store
        self.remote_store = remote_store
        self.local_store = local_store
        self.model_tracker = model_tracker

    async def _get_metadata(self, hotkey: str) -> ModelMetadata:
        """Get metadata about a model by hotkey"""
        return await self.metadata_store.retrieve_model_metadata(hotkey)

    async def sync_model(self, hotkey: str):
        """Updates local model for a hotkey if out of sync."""
        # Get the metadata for the miner.
        metadata = await self._get_metadata(hotkey)

        # Check what model id the model tracker currently has for this hotkey.
        tracker_model_id = self.model_tracker.get_model_id_for_miner_hotkey(hotkey)
        if metadata.id == tracker_model_id:
            return

        # Get the local path based on the local store.
        path = self.local_store.get_path(hotkey, metadata.id)

        # Otherwise we need to read the new model (which stores locally) based on the metadata.
        model = await self.remote_store.download_model(metadata.id, path)

        # Update the tracker
        self.model_tracker.on_miner_model_updated(hotkey, model.id)
