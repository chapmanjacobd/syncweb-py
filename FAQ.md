# Frequently Asked Questions

## Syncthing temporary files

Syncthing's default is to [remove partial transfers](https://docs.syncthing.net/users/config.html#config-option-options.keeptemporariesh) when rescanning after 24 hours have passed since the transfer attempt but in Syncweb I have it set to 8 days.

If people are running low on disk space we could make a button somewhere which finds and deletes '.syncthing\.*\.tmp' among other things
