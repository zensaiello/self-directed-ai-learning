#!/bin/bash

hitWebApp() {
  date
  for i in {1..$((5 + RANDOM % 15))} ; do
    curl -s http://localhost:5000/orders > /dev/null &
  done
  for i in {1..$((5 + RANDOM % 15))} ; do
    curl -s http://localhost:5000/orders/$((RANDOM % 5 + 1)) > /dev/null &
  done
  for i in {1..$((5 + RANDOM % 15))} ; do
    curl -s -X POST http://localhost:5000/orders/checkout > /dev/null &
  done
}


while [ 1 ] ; do
  sleep $((5 + RANDOM % 15)) && hitWebApp
  echo "---"
done
