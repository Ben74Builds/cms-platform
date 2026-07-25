docker stop service-coverage-monitoring-backend && docker rm service-coverage-monitoring-backend
docker build -t service-coverage-monitoring-backend . docker run -d --name service-coverage-monitoring-backend service-coverage-monitoring-backend
docker ps
docker exec -it service-coverage-monitoring-backend /bin/sh