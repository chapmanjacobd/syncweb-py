# Syncweb

## An offline-first distributed web

> This ‘World Wide Web’ was just a lame text format and a lot of connected directories.
>
> Ted Nelson

## Install

Requires syncthing v2 to be installed in the PATH (or as a static binary in the same folder that you run syncweb commands in)

```sh
pip install syncweb
```

## Usage

Start your syncweb cluster by creating your first folder

```sh
$ syncweb create audio/

sync://audio#CKTVWGQ-XBRFFRH-YTRPQ5G-YDA5YXI-N66GA5J-XVBGEZ3-PD56G6Y-N7TEAQC
Added 1 folder
```

Share your new folder with someone else

```sh
$ syncweb join sync://audio#CKTVWGQ-XBRFFRH-YTRPQ5G-YDA5YXI-N66GA5J-XVBGEZ3-PD56G6Y-N7TEAQC
Added 1 device
Added 1 folder
Local Device ID: NXL7XBL-VPNDOSR-QXU7WI7-NEUI65A-TWN7YGT-WS2U457-NTZNGB4-J6IYDQH
```

...you will also need to accept their device ID

```sh
$ syncweb accept NXL7XBL-VPNDOSR-QXU7WI7-NEUI65A-TWN7YGT-WS2U457-NTZNGB4-J6IYDQH
Added 1 device
```

### List files

```sh
$ syncweb ls --long audio/
Type       Size      Modified  Name
-----------------------------------
d        2.7GiB  06 Oct 20:56 Recordings/
d        3.2MiB  28 Jul  2022 Documentation/
```

### Find files

```sh
$ syncweb find --type=f --ext MKA --size=-20M --min-depth=2 Test
audio/Recordings/TestRecording_1.mka
audio/Recordings/TestRecording_22.mka
audio/Recordings/TestRecording_23.mka
...

# shorthand
$ syncweb find -tf -eMKA -S=-20M -d=+2 Test
```

### Sort

```sh
$ syncweb find -tf -eMKA -S=-20M -d=+2 Test | syncweb sort "balanced,frecency" | tee download_list.txt
audio/Recordings/TestRecording_23.mka
audio/Recordings/TestRecording_22.mka
audio/Recordings/TestRecording_1.mka
```

### Download

```sh
$ cat download_list.txt | syncweb download --yes
Download Summary:
---------------------------------------------------------------------------------------
Folder ID    Files   Total Size       Usable      Pending       Buffer  Shared   Status
---------------------------------------------------------------------------------------
audio           87     216.9MiB     114.6GiB            - 18.4GiB (1%)      No       OK
---------------------------------------------------------------------------------------
TOTAL           87     216.9MiB
---------------------------------------------------------------------------------------

Mark 87 files (216.9MiB) for download? [y/N]:
```

### Debugging

You can start another instance of Syncweb like this:

```sh
syncweb --home=/tmp/1/ join sync://test#CKTVWGQ-XBRFFRH-YTRPQ5G-YDA5YXI-N66GA5J-XVBGEZ3-PD56G6Y-N7TEAQC
syncweb --home=/tmp/1/ repl
```

## Future Aspirations

### What Syncweb is

Syncweb builds on top of Syncthing as an opinionated selective-sync configuration helper.

The advantages to using it are that it is offline first. You can download a whole website and use the site fully offline. When you come back online the new changes and updates will be synced and your comments and interactions will be automatically uploaded. It is delay-tolerant.

The disadvantage is that browser support for Syncweb URLs is virtually non-existant at this time. I have no plans to work on this aspect. Feel free to lead the charge!

The other really big disadvantage is that Syncweb is fragmented. But this limitation encourages small, productive, file-sharing groups! See what other people are sharing and find a group that matches your interests.

### What Syncweb is not

Syncweb will never replace your online banking app. While it may be possible to write something equivalent, I imagine doing so will be very clunky. The traditional web has very mature patterns for building. Requests are atomically mapped out across multiple services.

The traditional web has a robust line of authority via the Domain Name System so you can easily know whether you are on your bank's website or not. Syncweb has left this authority up to the community. Syncthing does not have a built-in certificate revocation mechanism like Certificate Authorities (CAs) do. You control the trust relationships of your devices directly.

### Links

> For example, a browser can be used in AFS by using “file://” rather than “http://” in addresses.  All of the powerful caching and consistence-maintenance machinery that is built into AFS would then have been accessible through a user-friendly tool that has eventually proved to be enormously valuable.  It is possible that the browser and AFS could have had a much more symbiotic evolution, as HTTP and browsers eventually did.
>
> Mahadev Satyanarayanan

```plain
      _____________
     '-------------.`-.
        /..---..--.\\  `._________________________________________
       //||   ||   \\\   `-\\-----\\-----\\-----\\-----\\-----\\--\
   __.'/ ||   ||    \\\     \\     \\     \\     \\     \\     \\  \
  /   /__||___||___.' \\     \\     \\     \\     \\     \\     \\ |
  |       |  -|        \\     \\     \\     \\     \\     \\     \\/
  |       |___|________ \\     \\     \\     \\     \\     \\_.-'
  [ ____ /.-----------.\ \\     \\     \\     \\     \\   .'
 | |____|/ .-'''''''-. \\ \\     \\     \\ .-'''''''-.\\_/
 | |____|.'           '.\\ \\____....----.'           '.
 | |___ /    .-----.    \\\______....---/    .-----.    \
 | |___|    / o o o \    \|============|    / o o o \    \
 | |__ |   | o     o |   ||____________|   | o     o |   |
[_.|___\    \ o o o /    |          LGB\    \ o o o /    |
  .  .  \    '-----'    /  .   ..  . .  \    '-----'    /  . .
 .  .  . '.           .'   .  .   .   .  '.           .' .  .
 ..  .   . '-._ _ _.-'   .  .   .   .   .  '-._ _ _.-' . .

UNDER CONSTRUCTION
```
