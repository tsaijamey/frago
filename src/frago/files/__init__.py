"""Moving files around, for callers that cannot do it themselves.

Three verbs with unix's meanings — ``cp``, ``mv``, ``rm`` — split over three
modules: :mod:`frago.files.ops` does the work, :mod:`frago.files.guard` says what
is out of bounds for everyone, and :mod:`frago.files.trash` knows how to get
something into this machine's trash.

The layer exists because of a boundary elsewhere. A recipe runs inside a view of
the filesystem holding its own landing spot and nothing more
(:mod:`frago.recipes.isolation`), and the system trash lives in the owner's home
directory, outside every such view — so "delete this the way this machine deletes
things" was not expressible from inside a recipe at all. The platform
already had the door for this: a recipe asks the server to run a frago command,
and that command runs unconfined in the server's process tree
(``frago.server.routes.bus.bus_frago``). What was missing was the commands.
"""

from frago.files.guard import Refused
from frago.files.ops import Done, Failed, Report, copy, move, remove

__all__ = ["Done", "Failed", "Refused", "Report", "copy", "move", "remove"]
