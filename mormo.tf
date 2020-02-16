# declare any input variables

# create docker volume resource

# create docker network resource

# Configure the Docker provider
provider "docker" {
  host = "tcp://127.0.0.1:2376/"
}

resource "docker_container" "app" {
  depends_on = [docker_container.redis]
  name  = "app"
  image = "joeystevens00/mormo:api"
  restart = "always"
  ports {
    external = "8001"
    internal = "8001"
  }
  env = [
    "REDIS_HOST=redis",
    "REDIS_PORT=6379",
  ]
  links = ["redis"]
}

resource "docker_container" "redis" {
  hostname = "redis"
  domainname = "redis"
  name  = "redis"
  image = "redis"
  restart = "always"
  ports {
    internal = "6379"
  }
}
