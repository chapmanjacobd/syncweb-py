#!/bin/sh

syncweb find -tf -eZIM -S-10M
syncweb find -tf -S+1G toast
./simple_wishlist.sh simple_wishlist.txt
