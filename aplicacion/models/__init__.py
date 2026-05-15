from aplicacion import db
from aplicacion.models.proceso1 import Proceso1Job, Proceso1Source, Proceso1SubprocessState
from aplicacion.models.proceso1_corto import Proceso1CortoJob, Proceso1CortoSource, Proceso1CortoSubprocessState
from aplicacion.models.proceso2 import Proceso2Job, Proceso2SubprocessState
from aplicacion.models.proceso2_corto import Proceso2CortoJob, Proceso2CortoSubprocessState
from aplicacion.models.proceso3 import Proceso3Job, Proceso3SubprocessState
from aplicacion.models.proceso3_corto import Proceso3CortoJob, Proceso3CortoSubprocessState
from aplicacion.models.proceso4 import (
    Proceso4AudioTrack,
    Proceso4Job,
    Proceso4MusicTemplate,
    Proceso4MusicTemplateItem,
    Proceso4SceneMedia,
    Proceso4SubprocessState,
)
from aplicacion.models.proceso4_corto import Proceso4CortoJob, Proceso4CortoSubprocessState, Proceso4CortoSceneMedia, Proceso4CortoAudioTrack
from aplicacion.models.proceso5 import Proceso5Job, Proceso5SubprocessState
from aplicacion.models.clip_library import ClipLibraryItem, ClipLibraryUsage


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)

    def __repr__(self):
        return f'<User {self.username}>'


__all__ = [
    'User',
    'Proceso1Job',
    'Proceso1Source',
    'Proceso1SubprocessState',
    'Proceso1CortoJob',
    'Proceso1CortoSource',
    'Proceso1CortoSubprocessState',
    'Proceso2Job',
    'Proceso2SubprocessState',
    'Proceso2CortoJob',
    'Proceso2CortoSubprocessState',
    'Proceso3Job',
    'Proceso3SubprocessState',
    'Proceso3CortoJob',
    'Proceso3CortoSubprocessState',
    'Proceso4Job',
    'Proceso4SubprocessState',
    'Proceso4SceneMedia',
    'Proceso4AudioTrack',
    'Proceso4MusicTemplate',
    'Proceso4MusicTemplateItem',
	'Proceso4CortoJob',
	'Proceso4CortoSubprocessState',
	'Proceso4CortoSceneMedia',
	'Proceso4CortoAudioTrack',
	'Proceso5Job',
    'Proceso5SubprocessState',
    'ClipLibraryItem',
    'ClipLibraryUsage',
]
