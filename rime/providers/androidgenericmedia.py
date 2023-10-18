# This software is released under the terms of the GNU GENERAL PUBLIC LICENSE.
# See LICENSE.txt for full details.
# Copyright 2023 Telemarq Ltd

"""
A provider which finds any media on the device not already found by other providers.
"""
from datetime import datetime
from dataclasses import dataclass

from ..provider import Provider
from ..event import MediaEvent, GenericEventInfo
from ..media import MediaData

from . import providernames
from .providernames import ANDROID_GENERIC_MEDIA, ANDROID_GENERIC_MEDIA_FRIENDLY

from ..metadata import get_fs_metadata


@dataclass
class DirentryProviderInfo:
    provider_name: str
    is_user_content: bool


_DIRENTRY_TO_PROVIDER_PREFIXES = {
    '/sdcard/Android/data/com.hmdglobal.camera2/': DirentryProviderInfo(providernames.ANDROID_CAMERA2_HMDGLOBAL, False),
    '/sdcard/DCIM/Camera/': DirentryProviderInfo(providernames.ANDROID_CAMERA, True),
    '/sdcard/WhatsApp/Media/': DirentryProviderInfo(providernames.ANDROID_WHATSAPP, True),
    '/sdcard/com.whatsapp/files/': DirentryProviderInfo(providernames.ANDROID_WHATSAPP, False),
}


def _guess_provider_for_entity(category) -> DirentryProviderInfo | None:
    for prefix, info in _DIRENTRY_TO_PROVIDER_PREFIXES.items():
        if category.startswith(prefix):
            return info

    return None


class AndroidGenericMedia(Provider):
    NAME = ANDROID_GENERIC_MEDIA
    FRIENDLY_NAME = ANDROID_GENERIC_MEDIA_FRIENDLY

    PII_FIELDS = []

    def __init__(self, fs):
        self.fs = fs

    @classmethod
    def from_filesystem(cls, fs):
        return cls(fs)

    def subset(self, subsetter, events, contacts):
        """
        Create a subset using the given events and contacts.
        """
        return None

    def all_files(self):
        # TODO
        return []

    def search_events(self, device, filter_):
        """
        Search for events matching ``filter_``, which is an EventFilter.
        """
        fs_metadata = get_fs_metadata(self.fs)

        for direntry in self.fs.walk('/sdcard'):
            metadata = fs_metadata.get(self.fs, direntry)
            if not metadata or not metadata.filetype:
                continue

            mime = metadata.filetype.mime

            if mime.startswith('image/') or mime.startswith('video/'):
                category = self.fs.dirname(direntry.path)

                # Attempt to label the provider. We either label it as definitively coming from a
                # specific provider, or, if it's user or unknown content, we default to the
                # unknown contact.
                direntry_provider_info = _guess_provider_for_entity(category)
                if direntry_provider_info and not direntry_provider_info.is_user_content:
                    sender = device.provider_contact(direntry_provider_info.provider_name)
                    is_user_generated = False
                else:
                    sender = device.unknown_contact
                    is_user_generated = True

                generic_event_info = GenericEventInfo(
                    category=category,
                    is_user_generated=is_user_generated,
                )

                yield MediaEvent(
                    mime_type=mime,
                    local_id=direntry.path,
                    id_=direntry.path,
                    timestamp=datetime.fromtimestamp(direntry.stat().st_ctime),
                    generic_event_info=generic_event_info,
                    provider=self,
                    sender=sender,
                )

    def search_contacts(self, filter_):
        """
        Return a list of Contacts matching ``filter_``.
        """
        return []

    def get_media(self, local_id) -> MediaData:
        """
        return a MediaData object supplying the picture, video, sound, etc identified by 'local_id'.
        """
        fs_metadata = get_fs_metadata(self.fs)
        direntry = self.fs.path_to_direntry(local_id)
        metadata = fs_metadata.get(self.fs, direntry)

        return MediaData(
            mime_type=metadata.filetype.mime,
            handle=self.fs.open(direntry.path),
            length=direntry.stat().st_size,
        )
