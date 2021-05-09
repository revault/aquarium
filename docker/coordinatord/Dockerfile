FROM rust:latest as builder

RUN git clone https://github.com/revault/coordinatord \
&& cd coordinatord \
&& cargo install --path .


VOLUME ["/home/.revault_coordinatord"]

EXPOSE 8383

COPY "entrypoint.sh" .
RUN /bin/sh -c "chmod +x entrypoint.sh"
