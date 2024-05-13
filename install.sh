#!/bin/bash

SERVICE_NAME="sphero"
INSTALL_DIR="/opt/$SERVICE_NAME"

# Install the required packages
sudo apt-get update
sudo apt-get install -y libopenjp2-7-dev python3 python3-pip pigpio
if [ $? -ne 0 ]; then
    echo "Failed to install python3 and python3-pip"
    exit 1
fi

# Install the required python packages
pip3 install --user --break-system-packages -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Failed to install the required python packages"
    exit 1
fi

# enable interfaces
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_rgpio 0

sudo systemctl enable pigpiod

# Check if the bluetooth is enabled
if [ $(echo $(bluetoothctl list) | wc -l) -eq 0 ]; then
    echo "No bluetooth devices found"
    exit 1
fi

# Copy the files to the /opt directory
sudo mkdir -p $INSTALL_DIR
sudo cp main.py $INSTALL_DIR

# Register the service
sed -i "s|INSTALL_DIR|$INSTALL_DIR|g" sphero.service
sudo cp sphero.service /etc/systemd/system/$SERVICE_NAME.service
if [ $? -ne 0 ]; then
    echo "Failed to copy the service file"
    exit 1
fi

sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
if [ $? -ne 0 ]; then
    echo "Failed to enable the service"
    exit 1
fi

sudo raspi-config nonint enable_overlayfs 0
if [ $? -ne 0 ]; then
    echo "Failed to enable overlayfs"
    exit 1
else
    echo "File system will be read-only after reboot."
fi

echo "Successfully installed the $SERVICE_NAME.service"
echo "System will reboot in 5 seconds"
sleep 5
sudo reboot