#!/bin/sh

sudo apt-get install apt-transport-https ca-certificates
sudo wget -O /etc/apt/trusted.gpg.d/opensky.gpg https://opensky-network.org/files/firmware/opensky.gpg.pub
sudo bash -c "echo deb https://opensky-network.org/repos/debian opensky custom > /etc/apt/sources.list.d/opensky.list"

wget https://www.flightaware.com/adsb/piaware/files/packages/pool/piaware/f/flightaware-apt-repository/flightaware-apt-repository_1.2_all.deb
sudo dpkg -i flightaware-apt-repository_1.2_all.deb

sudo apt update
sudo apt-get install piaware opensky-feeder dump1090-fa dump978-fa
