# Syncweb

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

## An offline-first distributed web

> This ‘World Wide Web’ was just a lame text format and a lot of connected directories.
>
> Ted Nelson

### What Syncweb is

Syncweb is first and foremost file and folder oriented. The advantages to using it are that it is offline first. You can download a whole website and use the site fully offline. When you come back online the new changes and updates will be synced and your comments and interactions will be automatically uploaded. It is delay-tolerant.

The disadvantage is that browser support for Syncweb URLs is virtually non-existant at this time. I have no plans to work on this aspect. Feel free to lead the charge!

The other really big disadvantage is that Syncweb is fragmented. But this limitation encourages small, productive, file-sharing groups! See what other people are sharing and find a group that matches your interests.

### What Syncweb is not

Syncweb will never replace your online banking app. While it may be possible to write something equivalent, I imagine doing so will be very clunky. The traditional web has very mature patterns for building. Requests are atomically mapped out across multiple services.

The traditional web has a robust line of authority via the Domain Name System so you can easily know whether you are on your bank's website or not. Syncweb has left this authority up to the community. Syncthing does not have a built-in certificate revocation mechanism like Certificate Authorities (CAs) do. You control the trust relationships of your devices directly.

## How to use

> It doesn't matter much who invented the microprocessor, the mouse, TCP/IP or the World Wide Web; nor does it matter what ideas were behind these inventions. What matters is who uses them. Only when users start to express themselves with these technical innovations do they truly become relevant to culture at large.

- drx, olia

## Differences from Syncthing

- Selective sync
