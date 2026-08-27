# Step 02 Docker Linux Container Setup

## Docker Version
![Docker version](./screenshots/docker-version.png)

## Hello World Output
![Hello world](./screenshots/hello-world-output.png)

## Cat /etc/os-release
![cat /etc/os-release](./screenshots/cat-etc-os-release.png)

## docker ps -a before
![Docker before](./screenshots/docker-ps-a-before.png)

## docker ps -a after
![Docker after](./screenshots/docker-ps-a-after.png)

## The difference between a Docker image and a Docker container.

The difference between a Docker image and a Docker container is the image is a read only template, while the container is the instance created from the image. The Docker image has the application code and everything needed to setup the environment, and the container is what actually runs and where you can run all of the commands. One way that I like to think about it is as a recipe and a cooked meal. The Docker image is the recipe that never changes, and the container is the meal you are able to make from it. You are able to use it, change it, and at the end of the day you can throw it away once done. 