FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY ["ApiGateway.csproj", "./"]
RUN dotnet restore "./ApiGateway.csproj"
COPY . .
RUN dotnet publish "ApiGateway.csproj" -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app/publish .
# Ensure Ocelot configuration is present in the runtime image
COPY ocelot.json /app/ocelot.json
ENV ASPNETCORE_URLS=http://+:80
EXPOSE 80
ENTRYPOINT ["dotnet", "ApiGateway.dll"]
